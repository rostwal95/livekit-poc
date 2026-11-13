ARG NODE_IMAGE
ARG NGINX_IMAGE
FROM ${NODE_IMAGE} AS build
WORKDIR /app
RUN npm install --global pnpm@12.18.0
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/local-console/package.json ./apps/local-console/package.json
COPY projects/channel-continuity/package.json ./projects/channel-continuity/package.json
COPY projects/delegation-reliability/specialist-ts/package.json ./projects/delegation-reliability/specialist-ts/package.json
RUN pnpm install --frozen-lockfile
COPY apps/local-console ./apps/local-console
RUN pnpm --filter @livekit-ecosystem/local-console build
FROM ${NGINX_IMAGE} AS runtime
COPY --from=build /app/apps/local-console/dist /usr/share/nginx/html
COPY apps/local-console/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
