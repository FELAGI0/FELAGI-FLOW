/**
 * Форматирование времени для UI запусков (5.C.1).
 *
 * Оба помощника — чистые функции над ISO-строками/Date, чтобы их можно было
 * тестировать без DOM. `now` передаётся параметром для детерминированных тестов.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Относительное время в прошлое: «5 минут назад», «2 часа назад», «3 дня назад».
 * Для будущих моментов — «через …». Меньше минуты — «только что».
 */
export function formatRelative(date: string | Date, now: Date = new Date()): string {
    const target = typeof date === "string" ? new Date(date) : date;
    const diff = now.getTime() - target.getTime();
    const past = diff >= 0;
    const abs = Math.abs(diff);

    if (abs < MINUTE) return "только что";

    const { value, unit } = pickUnit(abs);
    const phrase = pluralize(value, unit);
    return past ? `${phrase} назад` : `через ${phrase}`;
}

interface UnitValue {
    value: number;
    unit: "минута" | "час" | "день";
}

function pickUnit(absMs: number): UnitValue {
    if (absMs < HOUR) return { value: Math.floor(absMs / MINUTE), unit: "минута" };
    if (absMs < DAY) return { value: Math.floor(absMs / HOUR), unit: "час" };
    return { value: Math.floor(absMs / DAY), unit: "день" };
}

/** Русские формы множественного числа: 1 минута, 2 минуты, 5 минут. */
function pluralize(value: number, unit: "минута" | "час" | "день"): string {
    const mod10 = value % 10;
    const mod100 = value % 100;
    const isFew = mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14);
    const isOne = mod10 === 1 && mod100 !== 11;

    const forms: Record<typeof unit, [string, string, string]> = {
        минута: ["минута", "минуты", "минут"],
        час: ["час", "часа", "часов"],
        день: ["день", "дня", "дней"],
    };
    const [one, few, many] = forms[unit];
    const word = isOne ? one : isFew ? few : many;
    return `${value} ${word}`;
}

/**
 * Длительность между двумя моментами: «1.2s», «15.4s», «2m 3s», «1h 2m».
 * Если end нет (запуск не завершён) — null.
 */
export function formatDuration(
    start: string | Date | null,
    end: string | Date | null,
): string | null {
    if (!start || !end) return null;
    const startMs = (typeof start === "string" ? new Date(start) : start).getTime();
    const endMs = (typeof end === "string" ? new Date(end) : end).getTime();
    const seconds = (endMs - startMs) / 1000;
    if (seconds < 0) return null;

    if (seconds < 60) {
        // до минуты — с десятыми: «0.0s», «1.2s», «15.4s»
        return `${seconds.toFixed(1)}s`;
    }
    const total = Math.round(seconds);
    const minutes = Math.floor(total / 60);
    const restSeconds = total % 60;
    if (minutes < 60) {
        return restSeconds === 0 ? `${minutes}m` : `${minutes}m ${restSeconds}s`;
    }
    const hours = Math.floor(minutes / 60);
    const restMinutes = minutes % 60;
    return restMinutes === 0 ? `${hours}h` : `${hours}h ${restMinutes}m`;
}

/** Короткий id: первые 8 символов (для таблиц и заголовков). */
export function shortId(id: string): string {
    return id.slice(0, 8);
}