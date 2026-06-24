import { EventEmitter } from 'events';

export interface ServerConfig {
    host: string;
    port: number;
    tls?: boolean;
}

export type RequestHandler = (req: Request, res: Response) => void;

export enum LogLevel {
    DEBUG,
    INFO,
    WARN,
    ERROR,
}

// Server manages HTTP connections.
export class Server {
    private config: ServerConfig;

    constructor(config: ServerConfig) {
        this.config = config;
    }

    start(): void {
        console.log(`Listening on ${this.config.host}:${this.config.port}`);
    }
}

export abstract class BasePlugin {
    abstract init(): void;
}

export function createServer(config: ServerConfig): Server {
    return new Server(config);
}

export const DEFAULT_PORT: number = 8080;

export const handleRequest: RequestHandler = (req, res) => {
    res.end('OK');
};

export default class App {
    run() {}
}
