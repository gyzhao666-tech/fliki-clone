# Track-28 · frontend Next.js 16 多阶段镜像
# 阶段 1 builder：装 deps + 跑 `next build`，产物落到 .next/
# 阶段 2 runner ：仅留运行时所需文件 + node_modules，启 `next start`
# 不用 standalone output（避免改 next.config.ts；本 Track 不动业务代码）
FROM node:20-alpine AS builder

WORKDIR /app

# 优先复制 package.json + lockfile 让 npm ci 可被 layer cache
COPY package.json package-lock.json ./
RUN npm ci

# 拷剩下的源代码（.dockerignore 已过滤 node_modules / .next / .git 等）
COPY . .

# 跑生产构建（next 16 + next-intl plugin；配置文件是 .ts 由 next 内置 ts loader 处理）
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── Runtime ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# 仅拷贝运行时所需文件
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/package-lock.json ./package-lock.json
COPY --from=builder /app/next.config.ts ./next.config.ts
COPY --from=builder /app/tsconfig.json ./tsconfig.json
COPY --from=builder /app/postcss.config.mjs ./postcss.config.mjs
COPY --from=builder /app/messages ./messages
COPY --from=builder /app/public ./public
COPY --from=builder /app/src ./src
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3000

CMD ["npm", "run", "start"]
