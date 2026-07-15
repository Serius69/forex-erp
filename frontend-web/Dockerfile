# frontend-web/Dockerfile
# Stage 1: Build con Node 20
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci --silent

COPY . .
RUN npm run build

# Stage 2: Serve con nginx non-root — SPA (React Router)
# nginx-unprivileged (UID 101): obligatorio en el ecosistema porque los
# Deployments corren con runAsNonRoot: true (nginx:alpine root NO arranca).
# Puerto 3000 > 1024: un proceso non-root no puede bind a 80.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS production

USER root
COPY --from=builder /app/dist /usr/share/nginx/html

RUN printf 'server {\n\
    listen 3000;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    server_tokens off;\n\
    add_header X-Content-Type-Options "nosniff" always;\n\
    add_header X-Frame-Options "DENY" always;\n\
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n\
    add_header Cross-Origin-Opener-Policy "same-origin" always;\n\
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
    location ~* \\.(js|css|png|jpg|ico|svg|woff2?)$ {\n\
        expires 1y;\n\
        add_header Cache-Control "public, immutable";\n\
        add_header X-Content-Type-Options "nosniff" always;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

USER 101

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
