import { readFile } from 'fs';
import path from 'path';
const lodash = require('lodash');

// Greet returns a greeting string.
export function greet(name) {
    return `Hello, ${name}!`;
}

export class Logger {
    constructor(prefix) {
        this.prefix = prefix;
    }

    log(msg) {
        console.log(`${this.prefix}: ${msg}`);
    }
}

export const MAX_SIZE = 1024;

export const transform = (data) => {
    return data.map(x => x * 2);
};

export default function main() {
    greet('world');
}

export { readFile, path };
