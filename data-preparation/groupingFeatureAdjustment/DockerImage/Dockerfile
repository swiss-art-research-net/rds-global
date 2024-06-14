FROM node:14
# Create app directory
WORKDIR usr/src/app
# COPY ./entryPoint.sh ./
COPY ./package.json ./
COPY ./transform.js ./
COPY data ./data
COPY output ./output
COPY data ./data/
RUN npm install
CMD ["npm", "run", "start"]
