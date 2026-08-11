FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Vite bakes import.meta.env.VITE_* values in at the `npm run build` step
# below, reading them from the process env -- an ARG alone isn't visible
# there, so it must be promoted to ENV first.
ARG VITE_DAILY_NOTE_FOLDER=daily
ENV VITE_DAILY_NOTE_FOLDER=$VITE_DAILY_NOTE_FOLDER
ARG VITE_TEMPLATES_FOLDER=templates
ENV VITE_TEMPLATES_FOLDER=$VITE_TEMPLATES_FOLDER
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
