import { useCallback, useRef } from 'react';

interface UseRovingRadioGroupOptions {
  optionCount: number;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  disabled?: boolean;
}

// WAI-ARIA radiogroup pattern, "selection follows focus": arrow keys move
// focus AND selection together, matching native <input type="radio"> group
// behavior. Roving tabindex means only one option (the selected one, or the
// first when none is selected yet) is ever a Tab stop.
export function useRovingRadioGroup({
  optionCount,
  selectedIndex,
  onSelect,
  disabled = false,
}: UseRovingRadioGroupOptions) {
  const itemRefs = useRef<(HTMLElement | null)[]>([]);

  const setItemRef = useCallback(
    (idx: number) => (el: HTMLElement | null) => {
      itemRefs.current[idx] = el;
    },
    []
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent, currentIndex: number) => {
      if (disabled || optionCount === 0) return;

      let nextIndex: number | null = null;
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        nextIndex = (currentIndex + 1) % optionCount;
      } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        nextIndex = (currentIndex - 1 + optionCount) % optionCount;
      }

      if (nextIndex === null) return;

      event.preventDefault();
      onSelect(nextIndex);
      itemRefs.current[nextIndex]?.focus();
    },
    [optionCount, onSelect, disabled]
  );

  const getTabIndex = useCallback(
    (idx: number) => (idx === (selectedIndex ?? 0) ? 0 : -1),
    [selectedIndex]
  );

  return { setItemRef, handleKeyDown, getTabIndex };
}
