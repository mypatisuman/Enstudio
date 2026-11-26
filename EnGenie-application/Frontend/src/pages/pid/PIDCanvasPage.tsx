import React, { useState, useEffect } from 'react';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import PIDCanvasView from '../../components/PIDStudio/PIDCanvasView';
import { onGraphChanged } from '../../features/canvas/graphEvents';

export default function PIDCanvasPage() {
  const [graphData, setGraphData] = useState<any>(() => {
    try {
      const stored = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
      return stored ? JSON.parse(stored) : { nodes: [], edges: [] };
    } catch {
      return { nodes: [], edges: [] };
    }
  });

  useEffect(() => {
    const unsubscribe = onGraphChanged(() => {
      try {
        const stored = localStorage.getItem('active_pid_graph');
        if (stored) setGraphData(JSON.parse(stored));
      } catch {}
    });
    return unsubscribe;
  }, []);

  return (
    <PIDStudioLayout isFlush>
      <div className="w-full h-full relative">
        <PIDCanvasView
          graph={graphData}
          onGraphUpdate={updated => {
            setGraphData(updated);
            localStorage.setItem('active_pid_graph', JSON.stringify(updated));
            sessionStorage.setItem('active_pid_graph', JSON.stringify(updated));
          }}
        />
      </div>
    </PIDStudioLayout>
  );
}
