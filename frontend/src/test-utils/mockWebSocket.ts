/**
 * Переиспользуемый мок WebSocket для тестов (5.C.2).
 *
 * Эмулирует браузерный WebSocket: очередь экземпляров, открытие, доставку
 * сообщений и закрытие. Ставится глобально через `install()` — хук и клиент
 * `connectExecutionLogs` создают `new WebSocket(...)`, и он перехватывается.
 */

export class MockWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    /** Все созданные сокеты в порядке появления. */
    static instances: MockWebSocket[] = [];

    readonly url: string;
    readyState: number = MockWebSocket.CONNECTING;

    onopen: ((event: Event) => void) | null = null;
    onmessage: ((event: MessageEvent<string>) => void) | null = null;
    onclose: ((event: CloseEvent) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;

    constructor(url: string) {
        this.url = url;
        MockWebSocket.instances.push(this);
    }

    // --- управление из теста ---------------------------------------------------

    /** Как сервер открыл соединение: вызывает onopen. */
    simulateOpen(): void {
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.(new Event("open"));
    }

    /** Прислать сообщение от сервера (объект сериализуется в JSON). */
    simulateMessage(payload: unknown): void {
        const event = { data: JSON.stringify(payload) } as MessageEvent<string>;
        this.onmessage?.(event);
    }

    /** Прислать «сырое» сообщение (для проверки обработки битого JSON). */
    simulateRawMessage(data: string): void {
        const event = { data } as MessageEvent<string>;
        this.onmessage?.(event);
    }

    /** Закрытие со стороны сервера с заданным кодом. */
    simulateClose(code = 1000): void {
        this.readyState = MockWebSocket.CLOSED;
        this.onclose?.({ code } as CloseEvent);
    }

    simulateError(): void {
        this.onerror?.(new Event("error"));
    }

    // --- интерфейс WebSocket ---------------------------------------------------

    close(code = 1000): void {
        if (this.readyState === MockWebSocket.CLOSED) return;
        this.readyState = MockWebSocket.CLOSED;
        this.onclose?.({ code } as CloseEvent);
    }

    send(): void {
        // клиент ничего не отправляет; метод есть для полноты интерфейса
    }

    // --- помощники для тестов --------------------------------------------------

    static reset(): void {
        MockWebSocket.instances = [];
    }

    static last(): MockWebSocket {
        const socket = MockWebSocket.instances.at(-1);
        if (!socket) throw new Error("MockWebSocket: ни одного сокета не создано");
        return socket;
    }

    /** Установить мок как глобальный WebSocket и вернуть функцию очистки. */
    static install(): () => void {
        MockWebSocket.reset();
        const original = globalThis.WebSocket;
        // структурно совместим с WebSocket там, где он используется
        globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
        return () => {
            globalThis.WebSocket = original;
        };
    }
}

/** Проверка, что установленный сейчас WebSocket — наш мок. */
export function asMock(socket: WebSocket): MockWebSocket {
    return socket as unknown as MockWebSocket;
}