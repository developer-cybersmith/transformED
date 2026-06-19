export type WebSocketEventType = 'status' | 'progress' | 'completed' | 'error';

export interface BaseEvent {
    type: WebSocketEventType;
}

export interface StatusEvent extends BaseEvent {
    type: 'status';
    status: string;
}

export interface ProgressEvent extends BaseEvent {
    type: 'progress';
    progress: number;
    currentStep: string;
}

export interface CompletedEvent extends BaseEvent {
    type: 'completed';
    lessonId: string;
}

export interface ErrorEvent extends BaseEvent {
    type: 'error';
    message: string;
}

export type TransformEDEvent = StatusEvent | ProgressEvent | CompletedEvent | ErrorEvent;

export type WebSocketCallback = (event: TransformEDEvent) => void;

// Used to provide testing instructions to the socket
export interface MockSocketOptions {
    simulateError?: boolean;
    errorStage?: string;
    fastForwardProcessing?: boolean; // strictly for dev testing if they don't want to wait
}
