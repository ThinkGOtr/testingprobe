import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useGuvenlikYoklamasi } from "./hooks";

describe("useGuvenlikYoklamasi", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("iş sürerken aralıkla yoklar, iş bitince durur", () => {
    const fn = vi.fn();
    const { rerender, unmount } = renderHook(({ etkin }) => useGuvenlikYoklamasi(etkin, fn, 1000), { initialProps: { etkin: true } });
    vi.advanceTimersByTime(3000);
    expect(fn).toHaveBeenCalledTimes(3);
    rerender({ etkin: false });
    vi.advanceTimersByTime(5000);
    expect(fn).toHaveBeenCalledTimes(3);
    unmount();
  });

  it("etkin değilken hiç yoklamaz", () => {
    const fn = vi.fn();
    renderHook(() => useGuvenlikYoklamasi(false, fn, 1000));
    vi.advanceTimersByTime(5000);
    expect(fn).not.toHaveBeenCalled();
  });
});
