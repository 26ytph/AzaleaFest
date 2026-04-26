const createNextIntlPlugin = require('next-intl/plugin')

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api-proxy/:path*',
        destination: `${process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'}/:path*`,
      },
    ]
  },
}

module.exports = withNextIntl(nextConfig)
