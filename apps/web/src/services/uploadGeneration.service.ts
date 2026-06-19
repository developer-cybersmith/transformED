import { MockWebSocketClient, MockSocketOptions, WebSocketCallback } from '../lib/websocket';

class UploadGenerationService {
    private socket: MockWebSocketClient | null = null;

    /**
     * Initializes the WebSocket connection.
     * This behaves identically to what a future FastAPI Socket wrapper would look like.
     */
    public connect() {
        if (!this.socket) {
            this.socket = new MockWebSocketClient();
            this.socket.connect();
        }
        return this.socket;
    }

    public disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
    }

    /**
     * Subscribes to realtime updates during the upload and processing phase.
     * @param callback Function to execute when events are received
     * @returns An unsubscribe closure allowing cleanup inside useEffect
     */
    public subscribe(callback: WebSocketCallback) {
        if (!this.socket) {
            throw new Error("UploadGenerationService: Connection not initialized before subscribing.");
        }
        this.socket.subscribe(callback);

        // Return friendly cleanup function automatically
        return () => this.socket?.unsubscribe(callback);
    }

    /**
     * Starts the mock backend generation pipeline on the server.
     */
    public startGeneration(file: File, options?: MockSocketOptions) {
        if (!this.socket) {
            throw new Error("UploadGenerationService: Cannot start generation, socket not connected.");
        }
        return this.socket.startGeneration(file, options);
    }
}

// Export singleton instance to handle global socket state across the app
export const uploadGenerationService = new UploadGenerationService();
