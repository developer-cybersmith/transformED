export const delay = (ms: number): Promise<void> => {
    return new Promise((resolve) => setTimeout(resolve, ms));
};

export const randomDelay = (min: number, max: number): Promise<void> => {
    const ms = Math.floor(Math.random() * (max - min + 1)) + min;
    return delay(ms);
};
