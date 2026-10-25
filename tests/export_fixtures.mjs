import {writeFileSync} from 'node:fs';
import {BUILTIN_TEMPLATES} from '../templates.js';
writeFileSync(process.argv[2],JSON.stringify(BUILTIN_TEMPLATES));
console.log(BUILTIN_TEMPLATES.length+' built-in template fixtures');
