import { useEffect, useRef, useState, useCallback } from 'react';

interface WSMessage {
  type: string;
  channel?: string;
  [key: string]: unknown;
}

interface UseWebSocketOptions {
  channels?: string[];
  onMessage?: (msg: WSMessage) => void;
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { channels = [], onMessage, autoReconnect = true, reconnectInterval = 3000 } = options;
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const ws = new WebSocket(`${protocol}//${host}:8000/api/v1/ws?token=${token}`);

    ws.onopen = () => {
      setIsConnected(true);
      channels.forEach((ch) => {
        ws.send(JSON.stringify({ action: 'subscribe', channel: ch }));
      });
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        setLastMessage(msg);
        onMessage?.(msg);
      } catch { /* ignore non-JSON */ }
    };

    ws.onclose = () => {
      setIsConnected(false);
      if (autoReconnect) {
        reconnectTimer.current = setTimeout(connect, reconnectInterval);
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [channels.join(','), autoReconnect, reconnectInterval]);

  const sendMessage = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { isConnected, lastMessage, sendMessage, disconnect };
}
