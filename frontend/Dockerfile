# Etap 1: Budowanie aplikacji (Node.js)
FROM node:20-alpine AS build

# Katalog roboczy
WORKDIR /app

# Kopiowanie plików konfiguracyjnych
COPY package*.json ./

# Instalacja zależności
RUN npm install

# Kopiowanie reszty kodu (z pominięciem node_modules dzięki .dockerignore - upewnij się, że .gitignore działa też dla dockera)
COPY . .

# Zbudowanie aplikacji
RUN npm run build

# Etap 2: Serwowanie plików statycznych (Nginx)
FROM nginx:alpine

# Usunięcie domyślnej konfiguracji Nginx
RUN rm /etc/nginx/conf.d/default.conf

# Skopiowanie naszej konfiguracji Nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Skopiowanie zbudowanych plików z etapu budowania do katalogu Nginx
COPY --from=build /app/dist /usr/share/nginx/html

# Port, na którym będzie nasłuchiwał Nginx
EXPOSE 8080

# Uruchomienie Nginx w tle (daemon off)
CMD ["nginx", "-g", "daemon off;"]
