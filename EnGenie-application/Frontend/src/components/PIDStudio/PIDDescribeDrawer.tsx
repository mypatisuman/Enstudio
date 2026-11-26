import React from 'react';
import { DescribePanel } from '../../features/describe/components/DescribePanel';

interface PIDDescribeDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  sessionId: string;
  onGraphUpdated?: (updatedGraph: any) => void;
}

export default function PIDDescribeDrawer({
  isOpen,
  onClose,
  sessionId,
  onGraphUpdated,
}: PIDDescribeDrawerProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      {/* Backdrop for easy closing */}
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity duration-300"
        onClick={onClose}
      />

      {/* Sliding Drawer Container */}
      <div className="relative w-full max-w-md sm:max-w-lg md:max-w-xl h-full shadow-2xl animate-in slide-in-from-right duration-300 z-10 flex flex-col">
        <DescribePanel
          projectId={sessionId}
          onClose={onClose}
          className="w-full h-full"
        />
      </div>
    </div>
  );
}
