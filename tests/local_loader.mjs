// Resolve browser-root module URLs during Node's pure logic tests.
const modules=new Set(['canvas.js','fonts.js','templates.js','design.js','shapes.js','editor-tools.js','scheduled-player.js']);
export async function resolve(specifier,context,next){if(specifier.startsWith('/')&&modules.has(specifier.slice(1)))return next(new URL('..'+specifier,import.meta.url).href,context);return next(specifier,context)}
