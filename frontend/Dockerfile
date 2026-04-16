# ETAP 1: Budowanie (Builder)
FROM node:22-alpine AS builder

# Domyślnie uderzamy we względną ścieżkę /api, którą przechwyci Nginx
ARG VITE_API_URL=/api 
ENV VITE_API_URL=$VITE_API_URL

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ETAP 2: Serwowanie (Nginx)
FROM nginx:alpine
# Kopiujemy zbudowaną apkę z pierwszego etapu
COPY --from=builder /app/dist /usr/share/nginx/html
# Kopiujemy naszą konfigurację Nginxa
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]