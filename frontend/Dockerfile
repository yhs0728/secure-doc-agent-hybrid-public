FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . ./
RUN npm run build

FROM nginx:1.29-alpine
ARG NGINX_CONFIG=nginx.microservices.conf
ENV NGINX_DNS=127.0.0.11
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx
ENV NGINX_ENVSUBST_FILTER=NGINX_DNS
COPY ${NGINX_CONFIG} /etc/nginx/templates/nginx.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8000
