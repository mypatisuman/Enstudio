import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

export default {
    darkMode: ["class"],
    content: [
        "./pages/**/*.{ts,tsx}",
        "./components/**/*.{ts,tsx}",
        "./app/**/*.{ts,tsx}",
        "./src/**/*.{ts,tsx}",
    ],
    prefix: "",
    theme: {
        container: {
            center: true,
            padding: '2rem',
            screens: {
                '2xl': '1400px'
            }
        },
        extend: {
            colors: {
                border: 'hsl(var(--border))',
                input: 'hsl(var(--input))',
                ring: 'hsl(var(--ring))',
                background: 'hsl(var(--background))',
                foreground: 'hsl(var(--foreground))',
                primary: {
                    DEFAULT: 'hsl(var(--primary))',
                    foreground: 'hsl(var(--primary-foreground))'
                },
                secondary: {
                    DEFAULT: 'hsl(var(--secondary))',
                    foreground: 'hsl(var(--secondary-foreground))'
                },
                destructive: {
                    DEFAULT: 'hsl(var(--destructive))',
                    foreground: 'hsl(var(--destructive-foreground))'
                },
                muted: {
                    DEFAULT: 'hsl(var(--muted))',
                    foreground: 'hsl(var(--muted-foreground))'
                },
                accent: {
                    DEFAULT: 'hsl(var(--accent))',
                    foreground: 'hsl(var(--accent-foreground))'
                },
                popover: {
                    DEFAULT: 'hsl(var(--popover))',
                    foreground: 'hsl(var(--popover-foreground))'
                },
                card: {
                    DEFAULT: 'hsl(var(--card))',
                    foreground: 'hsl(var(--card-foreground))'
                },
                'ai-primary': 'hsl(var(--ai-primary))',
                'ai-primary-glow': 'hsl(var(--ai-primary-glow))',
                'ai-secondary': 'hsl(var(--ai-secondary))',
                'ai-accent': 'hsl(var(--ai-accent))',
                'ai-success': 'hsl(var(--ai-success))',
                'ai-success-light': 'hsl(var(--ai-success-light))',
                'ai-warning': 'hsl(var(--ai-warning))',
                'ai-warning-light': 'hsl(var(--ai-warning-light))',
                'ai-error': 'hsl(var(--ai-error))',
                'ai-error-light': 'hsl(var(--ai-error-light))',
                'ai-blue': 'hsl(var(--ai-blue))',
                'ai-light-blue': 'hsl(var(--ai-light-blue))',
                sidebar: {
                    DEFAULT: 'hsl(var(--sidebar-background))',
                    foreground: 'hsl(var(--sidebar-foreground))',
                    primary: 'hsl(var(--sidebar-primary))',
                    'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
                    accent: 'hsl(var(--sidebar-accent))',
                    'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
                    border: 'hsl(var(--sidebar-border))',
                    ring: 'hsl(var(--sidebar-ring))'
                }
            },
            borderRadius: {
                lg: 'var(--radius)',
                md: 'calc(var(--radius) - 2px)',
                sm: 'calc(var(--radius) - 4px)'
            },
            keyframes: {
                'accordion-down': {
                    from: { height: '0' },
                    to: { height: 'var(--radix-accordion-content-height)' }
                },
                'accordion-up': {
                    from: { height: 'var(--radix-accordion-content-height)' },
                    to: { height: '0' }
                },
                'fade-up': {
                    from: { opacity: '0', transform: 'translateY(10px)' },
                    to: { opacity: '1', transform: 'translateY(0)' }
                },
                'fade-in': {
                    from: { opacity: '0' },
                    to: { opacity: '1' }
                },
                'slide-in-left': {
                    from: { opacity: '0', transform: 'translateX(-16px)' },
                    to: { opacity: '1', transform: 'translateX(0)' }
                },
                'slide-in-right': {
                    from: { opacity: '0', transform: 'translateX(16px)' },
                    to: { opacity: '1', transform: 'translateX(0)' }
                },
                'pop': {
                    '0%': { transform: 'scale(0.92)', opacity: '0' },
                    '60%': { transform: 'scale(1.03)', opacity: '1' },
                    '100%': { transform: 'scale(1)', opacity: '1' }
                },
                'shimmer': {
                    '0%': { backgroundPosition: '-200% 0' },
                    '100%': { backgroundPosition: '200% 0' }
                },
                'pulse-ring': {
                    '0%, 100%': { opacity: '0.6', transform: 'scale(1)' },
                    '50%': { opacity: '1', transform: 'scale(1.05)' }
                }
            },
            animation: {
                'accordion-down': 'accordion-down 0.2s ease-out',
                'accordion-up': 'accordion-up 0.2s ease-out',
                'fade-up': 'fade-up 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards',
                'fade-in': 'fade-in 0.25s ease forwards',
                'slide-in-left': 'slide-in-left 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards',
                'slide-in-right': 'slide-in-right 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards',
                'pop': 'pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards',
                'shimmer': 'shimmer 2s linear infinite',
                'pulse-ring': 'pulse-ring 2s ease-in-out infinite'
            }
        }
    },
    plugins: [tailwindcssAnimate],
} satisfies Config;
