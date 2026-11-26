export interface NodeKinds {
  instruments: string[];
  equipment: string[];
}

const DEFAULT_KINDS: NodeKinds = {
  instruments: [
    'Transmitter', 'Flow Transmitter', 'Pressure Transmitter', 'Temperature Transmitter', 'Level Transmitter',
    'Controller', 'Pressure Controller', 'Temperature Controller', 'Flow Controller', 'Level Controller',
    'Control Valve', 'Ball Valve', 'Gate Valve', 'Globe Valve', 'Check Valve', 'Butterfly Valve', 'Safety Valve',
    'Indicator', 'Switch', 'Alarm', 'Solenoid Valve', 'Orifice Plate', 'Thermowell'
  ],
  equipment: [
    'Pump', 'Centrifugal Pump', 'Positive Displacement Pump', 'Compressor', 'Centrifugal Compressor',
    'Vessel', 'Horizontal Vessel', 'Vertical Vessel', 'Tank', 'Storage Tank',
    'Heat Exchanger', 'Shell and Tube Exchanger', 'Plate Heat Exchanger', 'Reboiler', 'Condenser', 'Cooler',
    'Reactor', 'CSTR', 'Fixed Bed Reactor', 'Column', 'Distillation Column', 'Separator', 'Filter'
  ]
};

export async function getNodeKinds(): Promise<NodeKinds> {
  return DEFAULT_KINDS;
}

export async function getPageImagePath(sessionId: string): Promise<string | null> {
  if (!sessionId) return null;
  const stored = localStorage.getItem(`pid_bg_${sessionId}`) || sessionStorage.getItem(`pid_bg_${sessionId}`);
  if (stored) return stored;
  return null;
}
