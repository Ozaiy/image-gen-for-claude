// HTML files are bundled as text by esbuild (see scripts/build.mjs)
declare module "*.html" {
  const text: string;
  export default text;
}
