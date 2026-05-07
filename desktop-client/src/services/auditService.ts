const AUDIT_API_URL = "http://localhost:8080/api/audit/log";

interface AuditEvent {
  event: string;
  sessionId: string;
  hostId: string;
  clientIp: string;
  timestamp: string;
  metadata?: Record<string, any>;
}

class AuditService {
  private queue: AuditEvent[] = [];
  private isProcessing = false;

  private getLocalIp(): string {
    // In Tauri, we can use a command to get local IP
    // For now, return a placeholder; implement via Tauri command if needed
    return "127.0.0.1";
  }

  private buildEvent(event: string, sessionId: string, hostId: string, metadata?: Record<string, any>): AuditEvent {
    return {
      event,
      sessionId,
      hostId,
      clientIp: this.getLocalIp(),
      timestamp: new Date().toISOString(),
      metadata
    };
  }

  async enqueueEvent(event: string, sessionId: string, hostId: string, metadata?: Record<string, any>) {
    const auditEvent = this.buildEvent(event, sessionId, hostId, metadata);
    this.queue.push(auditEvent);
    this.processQueue();
  }

  private async processQueue() {
    if (this.isProcessing || this.queue.length === 0) return;
    this.isProcessing = true;

    while (this.queue.length > 0) {
      const event = this.queue.shift()!;
      await this.sendEvent(event);
    }

    this.isProcessing = false;
  }

  private async sendEvent(event: AuditEvent) {
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const response = await fetch(AUDIT_API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(event)
        });
        if (response.ok) return;
        console.warn(`Audit log failed [${response.status}] ${AUDIT_API_URL}`);
      } catch (error) {
        console.error(`Audit log request failed on attempt ${attempt}:`, error);
      }
      if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
}

export const auditService = new AuditService();
