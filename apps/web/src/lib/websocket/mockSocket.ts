import { EVENT_SEQUENCE } from './eventSequence';
import { createStatusEvent, createProgressEvent, createCompletedEvent, createErrorEvent } from './mockEvents';
import { MockSocketOptions, WebSocketCallback, TransformEDEvent } from './types';
import { randomDelay } from '../../mocks/utils/delay';

export class MockWebSocketClient {
    private isConnected = false;
    private listeners: WebSocketCallback[] = [];
    private processing = false;

    public connect() {
        this.isConnected = true;
        console.log("[MockWebSocket] Connected to simulation layer");
    }

    public disconnect() {
        this.isConnected = false;
        this.listeners = [];
        this.processing = false;
        console.log("[MockWebSocket] Disconnected");
    }

    public subscribe(callback: WebSocketCallback) {
        this.listeners.push(callback);
    }

    public unsubscribe(callback: WebSocketCallback) {
        this.listeners = this.listeners.filter(cb => cb !== callback);
    }

    private emit(event: TransformEDEvent) {
        if (!this.isConnected) return;
        this.listeners.forEach(cb => cb(event));
    }

    public async startGeneration(file: File, options?: MockSocketOptions) {
        if (!this.isConnected) throw new Error("Socket not connected");
        if (this.processing) return; // Prevent concurrent processing

        this.processing = true;
        try {
            for (const stage of EVENT_SEQUENCE) {
                if (!this.processing || !this.isConnected) break; // If disconnected mid-way

                // Emit status update immediately
                this.emit(createStatusEvent(stage.stepName));

                // Wait realistic latency sequence
                if (!options?.fastForwardProcessing) {
                    await randomDelay(stage.minDelayMs, stage.maxDelayMs);
                }

                // Emit progress update after completing the stage delay
                this.emit(createProgressEvent(stage.progressPercent, stage.stepName));

                // Inject simulated backend errors if requested
                if (options?.simulateError) {
                    const shouldFailNow = options.errorStage === stage.stepName || (!options.errorStage && stage.progressPercent > 50);
                    if (shouldFailNow) {
                        throw new Error(`Simulation Error: Processing failed during [${stage.stepName}]`);
                    }
                }
            }

            // If we made it to the end successfully
            if (this.processing && this.isConnected) {
                this.emit(createCompletedEvent(`lesson_${Date.now()}`));
            }
        } catch (err: any) {
            if (this.isConnected) {
                this.emit(createErrorEvent(err.message));
            }
        } finally {
            this.processing = false;
        }
    }
}
