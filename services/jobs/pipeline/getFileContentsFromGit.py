import base64
import requests
import hashlib
import json
import re
import os
import argparse

def getFileContentsFromGit(username, token, repo, path, localfile):
    folder = path.rsplit('/', 1)[0]
    file = path.rsplit('/', 1)[1]

    folderURL = 'https://api.github.com/repos/' + repo + '/contents/' + folder
    folderRequest = requests.get(folderURL, auth=(username, token))
    folderData = folderRequest.json()

    try:
        requestedFile = [d for d in folderData if d['name'] == file][0]
    except:
        sys.stderr.write("could not find file %s in path %s\n" % (file, folderURL))
        exit()

    # Check if file already exists locally and if size matches
    if os.path.exists(localfile):
        with open(localfile, 'rb') as f:
            localSize = os.path.getsize(localfile)
        if requestedFile['size'] == localSize:
            sys.stderr.write("File already exists locally and file size matches\n")
            exit()

    fileURL = 'https://api.github.com/repos/' + repo + '/git/blobs/' + requestedFile['sha']
    fileRequest = requests.get(fileURL, auth=(username, token))

    result = base64.b64decode(fileRequest.json()['content']).decode('UTF-8', 'ignore')
    if not "https://git-lfs.github.com/spec/v1" in result:
        with open(localfile, 'w', encoding='utf-8') as f:
            f.write(result)
    else:
        # Download from GIT LFS
        sha = re.findall(r'sha256:([a-z0-9]*)', result)[0]
        size = int(re.findall(r'size ([0-9]*)', result)[0])

        # Check if file already exists locally and if SHA and Size match
        if os.path.exists(localfile):
            with open(localfile, 'rb') as f:
                localSHA = hashlib.sha256(f.read()).hexdigest()
                localSize = os.path.getsize(localfile)
            if sha == localSHA and size == localSize:
                sys.stderr.write("File already exists locally and is up to date\n")
                exit()

        url = "https://github.com/" + repo + ".git/info/lfs/objects/batch"
        data = {
            'operation': 'download',
            'transfer': ['basic'],
            'objects': [
                {'oid': sha, 'size': size}
            ]}
        headers = {'Content-type': 'application/json', 'Accept': 'application/vnd.git-lfs+json'}

        r = requests.post(url, data=json.dumps(data), headers=headers, auth=(username, token))
        downloadurl = r.json()['objects'][0]['actions']['download']['href']

        response = requests.get(downloadurl)

        with open(localfile, 'w', encoding='utf-8') as f:
            f.write(response.content.decode('UTF-8', 'ignore'))

    sys.stderr.write("Done!\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get file contents from GitHub repository')
    parser.add_argument('username', help='GitHub username')
    parser.add_argument('token', help='GitHub personal access token')
    parser.add_argument('repo', help='Repository')
    parser.add_argument('path', help='Path to file')
    parser.add_argument('localfile', help='Local file path')

    args = parser.parse_args()

    getFileContentsFromGit(args.username, args.token, args.repo, args.path, args.localfile)
