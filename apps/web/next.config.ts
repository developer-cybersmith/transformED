import type { NextConfig } from 'next'

const config: NextConfig = {
  // Enable WASM for MediaPipe
  experimental: { serverActions: { allowedOrigins: ['localhost:3000'] } },
  webpack: (config) => {
    config.experiments = { ...config.experiments, asyncWebAssembly: true, layers: true }
    return config
  },
}

export default config
