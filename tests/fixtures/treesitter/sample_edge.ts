import { EventEmitter } from 'events';

export interface Container<T> {
    get(): T;
    set(value: T): void;
}

export class Box<T> implements Container<T> {
    private value: T;

    constructor(value: T) {
        this.value = value;
    }

    get(): T {
        return this.value;
    }

    set(value: T): void {
        this.value = value;
    }
}

export type IsString<T> = T extends string ? true : false;

export type Readonly<T> = {
    readonly [P in keyof T]: T[P];
};

export type StringOrNumber = string | number;

export type UserRecord = {
    id: number;
    name: string;
} & { createdAt: Date };

export namespace Validators {
    export function isEmail(value: string): boolean {
        return value.includes('@');
    }
}

export const COLORS = ['red', 'green', 'blue'] as const;

export async function loadConfig<T>(path: string): Promise<T> {
    return {} as T;
}

export function* counter(start: number = 0): Generator<number> {
    let n = start;
    while (true) {
        yield n++;
    }
}
