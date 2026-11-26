import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // src-tauri/target holds Rust build output, including JS assets that
  // tauri-codegen generates during a release build. Linting generated code
  // reports errors nobody can fix; only `dist` was ignored before, so the
  // count changed depending on whether a release build had been run.
  globalIgnores(['dist', 'src-tauri/target']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // _-prefixed args are the standard "intentionally unused" convention
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
  {
    // Validation harnesses under tests/ are not part of the shipped bundle
    // (tsconfig includes only src/) and are run directly by `node`. They read
    // rows straight out of SQLite as untyped JSON, so `any` at that boundary
    // is the accurate type, not a shortcut — declaring a shape there would
    // assert a guarantee the database does not give.
    files: ['tests/**/*.ts'],
    languageOptions: { globals: globals.node },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
])
