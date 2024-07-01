'use strict';

const fs = require('fs');
var levelup = require('levelup');
var leveldown = require('leveldown');
const path = require('path');
const N3 = require('n3');
const { DataFactory } = N3;
const { namedNode } = DataFactory;

const SAME_AS_PREDICATE = namedNode("http://schema.swissartresearch.net/ontology/rds#related");
const DATA_FOLDER = '/data/sameAsStatements/sources';
const OUTPUT_FOLDER = '/data/sameAsStatements/combined';
const HEAP_SIZE = 1000000;
const WRITING_STRING_SIZE = 1000000;

const db = levelup(leveldown('./processing_db'))

// Script work the following way
// We go by triples, expecting that dataset has only relation triples. All Iris we put in the
// map stored in the local database
// For each IRI we create (and put in the map) a list of same as elements.
// For IRIs from the same sameAs group these lists will be the same.
// Then we just serialize this map into the ttl, where reference iris for the groups
// are the first elements from the lists
// If you want to introduce the custom order you have to change the merging function
// And make script expect triples with types (not only relation triples as it implemented now)

function getQuadSets(quad) {
    return Promise.all([
        db.get(quad.subject.value).then(string => JSON.parse(string)).catch(() => undefined),
        db.get(quad.object.value).then(string => JSON.parse(string)).catch(() => undefined),
    ]).then(([subjectSet, objectSet]) => {
        return {
            subjectSet: { set: subjectSet, iri: quad.subject.value },
            objectSet: { set: objectSet, iri: quad.object.value }
        };
    });
}

// Merges two sameAs lists, then save it to DB
// Here you can introduce some ordering
// or implement the ordering before saving to the file
function mergeSetsAndSaveToDb(fetchedValues) {
    let subjectSet = fetchedValues.subjectSet.set;
    let subjectIri = fetchedValues.subjectSet.iri;
    let objectSet = fetchedValues.objectSet.set;
    let objectIri = fetchedValues.objectSet.iri;

    let mergedSet;
    if (subjectSet && objectSet) {
        if (subjectSet[0] !== objectSet[0]) {
            mergedSet = objectSet.concat(subjectSet);
        } else {
            mergedSet = subjectSet;
        }
    } else if (!subjectSet && !objectSet) {
        mergedSet  = [subjectIri, objectIri];
    } else if (subjectSet) {
        mergedSet = subjectSet;
        mergedSet.push(objectIri);
    } else {
        mergedSet = objectSet;
        mergedSet.push(objectIri);
    }
    const stringSet = JSON.stringify(mergedSet);
    const tasks = mergedSet.map(iri => ({ type: 'put', key: iri, value: stringSet }));
    return db.batch(tasks);
}

// In the first cycle of processing we just parse each file without processing
// To show errors first without waiting long time
function checkFile(filePath) {
    // Class
    function Checker(onEnd) {
        const writer = new require('stream').Writable({ objectMode: true });
        writer._write = (quad, encoding, done) => { done(); };
        writer.on('finish', () => { onEnd() });
        return writer;
    }

    return new Promise(resolve => {
        console.log(`Checking ${filePath}.`);
        const rdfStream = fs.ReadStream(filePath, 'utf8');
        const streamParser = new N3.StreamParser();
        rdfStream.pipe(streamParser);
        streamParser.pipe(new Checker(() => resolve()));
    })
}

// This function is called for each file - parse it, and store to the map
function processFile(filePath) {
    // Class
    function Processor(onEnd) {
        let heap = [];
        const writer = new require('stream').Writable({ objectMode: true });
        const processHeap = (done) => {
            let promise = Promise.resolve();
            // let processingIndex = 0;
            for (const q of heap) {
                promise = promise
                    .then(() => getQuadSets(q))
                    .then(sets => mergeSetsAndSaveToDb(sets));
                    // .then(() => console.log(`Processing quad. Quad: ${processingIndex++}`));
            }
            return promise.then(() => {
                // console.log(`Processing done`);
                heap = [];
                if (done) { done(); }
                return;
            });
        }
        writer._write = (quad, encoding, done) => {
            if (!quad) {
                done();
                // console.log(`Last quad.`);
                processHeap(done).then(() => onEnd());
            }
            if (heap.length > HEAP_SIZE) {
                processHeap(done);
            } else {
                heap.push(quad);
                // console.log(`Caching quad. Heap size ${heap.length}`);
                done();
            }
        };
        writer.on('finish', () => {
            // console.log(`Last quad.`);
            processHeap().then(() => onEnd());
        });
        return writer;
    }

    return new Promise(resolve => {
        console.log(`Process ${filePath}.`);
        const rdfStream = fs.ReadStream(filePath, 'utf8');
        const streamParser = new N3.StreamParser();
        rdfStream.pipe(streamParser);
        streamParser.pipe(new Processor(() => resolve()));
    })
}

// Stores results to ttl
function storeToTtl() {
    const createWriter = () => {
        return new N3.Writer({
            prefixes: {
                aat: 'http://vocab.getty.edu/aat/',
                loc_1: 'http://www.loc.gov/mads/rdf/v1#',
                loc_2: 'http://id.loc.gov/authorities/subjects/',
                skos: 'http://www.w3.org/2004/02/skos/core#',
                owl: 'http://www.w3.org/2002/07/owl#',
                rdf: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                rdfs: 'http://www.w3.org/2000/01/rdf-schema#',
                ulan: 'http://vocab.getty.edu/ulan/',
                gvp: 'http://vocab.getty.edu/ontology#',
                schema: 'http://schema.org/',
                wd: 'http://www.wikidata.org/entity/',
                wdt: 'http://www.wikidata.org/prop/direct/',
                rds: 'https://static.swissartresearch.net/',
                crmdig: 'http://www.ics.forth.gr/isl/CRMdig/',
            }
        });
    };

    const writeToFile = (result, fileId) => {
        fs.writeFile(path.resolve(__dirname, OUTPUT_FOLDER, fileId), result, err => {
            if (err) return console.log(err);
            console.log(`Writing to ${fileId} completed!`);
        });
    };

    // start reading map
    const readStream = db.createReadStream();
        
    let resultIndex = 0;
    let fileId = `sameAsStatements_${resultIndex++}.ttl`;
    let index = 0;
    let writer = createWriter();
    console.log(`Preparing data for ${fileId}.`);
    readStream.on('data', data => {
        if (index > WRITING_STRING_SIZE) {
            index = 0;
            console.log(`Writing graph to file ${fileId}`);
            writer.end((error, result) => {
                if (error) { console.log(error.message); }
                writeToFile(result, fileId);
            });
            writer = createWriter();
            fileId = `sameAsStatements_${resultIndex++}.ttl`;
            console.log(`Preparing data for ${fileId}.`);
        }
        const key = String.fromCharCode.apply(null, data.key);
        const sameAsSet = JSON.parse(data.value);
        // Here we get the first element of the list and put as a reference
        // You can introduce ordering here
        const reference = namedNode(sameAsSet[0]);
        if (key !== sameAsSet[0]) {
            return;
        }
        index++;
        for (let i = 1; i < sameAsSet.length; i++) {
            const sameAsInstance = namedNode(sameAsSet[i]);
            if (sameAsSet[0] !== sameAsSet[i]) {
                writer.addQuad(
                    reference,
                    SAME_AS_PREDICATE,
                    sameAsInstance,
                );
            }
        }
    })
    readStream.on('end', () => {
        console.log(`Writing graph to file ${fileId}`);
        writer.end((error, result) => {
            if (error) { console.log(error.message); }
            writeToFile(result, fileId);
        });
    });
}

let readingPromise = Promise.resolve();
fs.readdir(path.resolve(__dirname, DATA_FOLDER), (err, files) => {
    console.log(`Files in the data directory: ${files}`);
    if (files) {
        // Checking
        files.forEach(file => {
            readingPromise = readingPromise.then(() => checkFile(path.resolve(__dirname, DATA_FOLDER, file)))
        });
        // Processing
        files.forEach(file => {
            readingPromise = readingPromise.then(() => processFile(path.resolve(__dirname, DATA_FOLDER, file)))
        });
        readingPromise.then(() => storeToTtl());
    }
});
