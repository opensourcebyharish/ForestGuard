import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatTimestamp } from '../api/forestguard'

export interface EnvironmentalPoint {
  timestamp: string
  temperature: number | null
  humidity: number | null
  nodeId: string
  simulated: boolean
}

export default function EnvironmentalTrendChart({ data }: { data: EnvironmentalPoint[] }) {
  return <>
    <div className="environment-chart" role="img" aria-label="Temperature and humidity from recorded sensor readings">
      <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 12, right: 14, bottom: 2, left: -14 }}>
        <CartesianGrid stroke="#ffffff0d" vertical={false} />
        <XAxis dataKey="timestamp" tickFormatter={(value: string) => formatTimestamp(value)} tickLine={false} axisLine={false} tick={{ fill: '#788b84', fontSize: 9 }} minTickGap={28} />
        <YAxis yAxisId="temperature" tickLine={false} axisLine={false} tick={{ fill: '#e8a966', fontSize: 9 }} width={34} />
        <YAxis yAxisId="humidity" orientation="right" domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: '#59cde0', fontSize: 9 }} width={32} />
        <Tooltip labelFormatter={(value) => formatTimestamp(String(value))} content={({ active, payload, label }) => {
          if (!active || !payload?.length) return null
          const point = payload[0].payload as EnvironmentalPoint
          return <div className="risk-tooltip"><strong>{formatTimestamp(String(label))} · {point.nodeId}</strong><span>Temperature: {point.temperature === null ? 'Unavailable' : `${point.temperature.toFixed(1)} °C`}</span><span>Humidity: {point.humidity === null ? 'Unavailable' : `${point.humidity.toFixed(1)}%`}</span><small>{point.simulated ? 'SIMULATED DATA' : 'NON-SIMULATED DATA'}</small></div>
        }} />
        <Line yAxisId="temperature" dataKey="temperature" name="Temperature °C" stroke="#eda967" strokeWidth={1.8} dot={false} connectNulls={false} isAnimationActive={false} />
        <Line yAxisId="humidity" dataKey="humidity" name="Humidity %" stroke="#59cde0" strokeWidth={1.8} dot={false} connectNulls={false} isAnimationActive={false} />
      </LineChart>
      </ResponsiveContainer>
    </div>
    <ul className="sr-only" aria-label="Environmental sensor data">
      {data.map((point, index) => <li key={`${point.nodeId}-${point.timestamp}-${index}`}>{formatTimestamp(point.timestamp)} · {point.nodeId}: temperature {point.temperature === null ? 'unavailable' : `${point.temperature} degrees Celsius`}, humidity {point.humidity === null ? 'unavailable' : `${point.humidity} percent`}; {point.simulated ? 'simulated' : 'non-simulated'} data.</li>)}
    </ul>
  </>
}
