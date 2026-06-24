import EventEmitter from 'events';

export * from './utils';

export { EventEmitter as Emitter };

export async function fetchData(url) {
    const res = await fetch(url);
    return res.json();
}

export function* idGenerator() {
    let id = 0;
    while (true) {
        yield id++;
    }
}

export const { name: appName, version: appVersion } = { name: 'myapp', version: '1.0' };

export default new EventEmitter();
