import { EVENT_SEQUENCE } from './eventSequence';
import {
  createGenerationProgressMessage,
  createLessonReadyMessage,
  createErrorMessage,
} from './mockEvents';
import type { MockSocketOptions, WebSocketCallback } from './types';
import { randomDelay } from '../../mocks/utils/delay';

export class MockWebSocketClient {
  private isConnected = false;
  private listeners: WebSocketCallback[] = [];
  private processing = false;

  public connect() {
    this.isConnected = true;
    console.log('[MockWebSocket] Connected to simulation layer');
  }

  public disconnect() {
    this.isConnected = false;
    this.listeners = [];
    this.processing = false;
    console.log('[MockWebSocket] Disconnected');
  }

  public subscribe(callback: WebSocketCallback) {
    this.listeners.push(callback);
  }

  public unsubscribe(callback: WebSocketCallback) {
    this.listeners = this.listeners.filter(cb => cb !== callback);
  }

  private emit(event: Parameters<WebSocketCallback>[0]) {
    if (!this.isConnected) return;
    this.listeners.forEach(cb => cb(event));
  }

  public async startGeneration(file: File, options?: MockSocketOptions) {
    if (!this.isConnected) throw new Error('Socket not connected');
    if (this.processing) return;

    this.processing = true;
    const lessonId = `lesson_mock_${Date.now()}`;

    try {
      for (const stage of EVENT_SEQUENCE) {
        if (!this.processing || !this.isConnected) break;

        if (!options?.fastForwardProcessing) {
          await randomDelay(stage.minDelayMs, stage.maxDelayMs);
        }

        this.emit(createGenerationProgressMessage(
          lessonId,
          stage.stepName,
          stage.progressPercent,
          stage.stepName,
        ));

        if (options?.simulateError) {
          const shouldFailNow =
            options.errorStage === stage.stepName ||
            (!options.errorStage && stage.progressPercent > 50);
          if (shouldFailNow) {
            throw new Error(`Simulation error during [${stage.stepName}]`);
          }
        }
      }

      if (this.processing && this.isConnected) {
        this.emit(createLessonReadyMessage(lessonId));
      }
    } catch (err: unknown) {
      if (this.isConnected) {
        const message = err instanceof Error ? err.message : String(err);
        this.emit(createErrorMessage('MOCK_ERROR', message));
      }
    } finally {
      this.processing = false;
    }
  }
}
