FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://packagefeedproxy.microsoft.io/npm/ \
    && npm install
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:20-slim
ENV NODE_ENV=production PORT=3978
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://packagefeedproxy.microsoft.io/npm/ \
    && npm install --omit=dev
COPY --from=build /app/dist ./dist
EXPOSE 3978
CMD ["npm", "start"]
