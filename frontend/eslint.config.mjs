// ESLint flat config (ESLint 9 / Next 16; `next lint` was removed in Next 16).
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  ...nextVitals,
  globalIgnores([".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts"]),
  {
    rules: {
      // Keep the project's pre-upgrade policy: stale-closure deps are an error.
      "react-hooks/exhaustive-deps": "error",
      // eslint-plugin-react-hooks@7 (bundled by eslint-config-next@16) enables the
      // React Compiler rule suite at error by default. This app doesn't opt into the
      // compiler, and these rules flag deliberate idioms — the "latest callback" ref
      // and effect-scoped state resets in useRunStream / page.tsx. Off to preserve the
      // prior baseline; revisit if/when the compiler is adopted.
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      // react-hook-form's watch() is flagged as compiler-incompatible; advisory only
      // and irrelevant without the compiler.
      "react-hooks/incompatible-library": "off",
    },
  },
]);
