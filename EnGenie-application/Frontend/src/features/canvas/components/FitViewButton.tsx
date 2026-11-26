import React from 'react';
import { useReactFlow } from '@xyflow/react';
import { Maximize2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function FitViewButton() {
  const { fitView } = useReactFlow();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 px-2.5 text-xs font-medium text-slate-300 hover:text-white hover:bg-slate-800/80 gap-1.5"
      onClick={() => fitView({ padding: 0.2, duration: 400 })}
      title="Fit view to all nodes"
    >
      <Maximize2 className="h-3.5 w-3.5" />
      <span>Fit</span>
    </Button>
  );
}
