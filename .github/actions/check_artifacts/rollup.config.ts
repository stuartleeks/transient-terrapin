// See: https://rollupjs.org/introduction/

import commonjs from '@rollup/plugin-commonjs'
import nodeResolve from '@rollup/plugin-node-resolve'
import typescript from '@rollup/plugin-typescript'
import json from "@rollup/plugin-json"

const config = {
  input: 'src/index.ts',
  output: {
    esModule: true,
    file: 'dist/index.js',
    format: 'es',
    sourcemap: true,
    inlineDynamicImports: true,
    
  },
  plugins: [typescript({compilerOptions: {outDir:"./dist"}}), nodeResolve({ preferBuiltins: true }), commonjs(), json()]
}

export default config
