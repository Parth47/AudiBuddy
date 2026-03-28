import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Compress responses for faster transfer
  compress: true,

  // Optimize images served from Supabase storage
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**.supabase.co",
      },
    ],
  },

  // Disable unnecessary features that add bundle weight
  poweredByHeader: false,

  // Ensure dynamic pages aren't cached on the client side
  experimental: {
    staleTimes: {
      dynamic: 0,
    },
  },
};

export default nextConfig;
