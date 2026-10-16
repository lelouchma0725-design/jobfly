/** 全局 Loading：api() 自動觸發遮罩（灰化 + 轉盤）。 */

let _count = 0;
let _timer: number | null = null;
let _listeners: Array<(on: boolean) => void> = [];

export function onLoadingChange(fn: (on: boolean) => void) {
  _listeners.push(fn);
  return () => {
    _listeners = _listeners.filter((f) => f !== fn);
  };
}

function emit(on: boolean) {
  _listeners.forEach((f) => f(on));
}

/** 每次 API 請求開始/結束調用。請求超過 200ms 才顯示遮罩（避免閃爍）。 */
export function beginRequest() {
  _count += 1;
  if (_timer === null) {
    _timer = window.setTimeout(() => emit(true), 200);
  }
}

export function endRequest() {
  _count = Math.max(0, _count - 1);
  if (_count === 0 && _timer !== null) {
    window.clearTimeout(_timer);
    _timer = null;
    emit(false);
  }
}
