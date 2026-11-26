import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendTarget = env.VITE_BACKEND_URL || 'http://127.0.0.1:7071';
  const htmlBypass = (req: any) => {
    if (req.headers.accept?.includes('text/html')) {
      return '/index.html';
    }
  };

  return {
    base: '/',
    server: {
      host: "::",
      port: 8080,
      strictPort: false,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: true,
        },
        '/user': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
        '/login': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          bypass: htmlBypass,
        },
        '/logout': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
        '/register': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
        '/new-search': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
        '/submodel-mapping': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
        '/admin': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          bypass: htmlBypass,
        },
      }
    },
    plugins: [
      react(),
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    build: {
      assetsDir: '_assets',
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules')) {
              if (id.includes('jspdf')) {
                return 'vendor-jspdf';
              }
              if (id.includes('html2canvas')) {
                return 'vendor-html2canvas';
              }
              return 'vendor';
            }
          },
        },
      },
      chunkSizeWarningLimit: 1000,
    },
  };
});
