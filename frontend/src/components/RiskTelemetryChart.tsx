import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatTimestamp } from '../api/forestguard'

interface RiskPoint {
  time: string
  timeMs: number
  score: number | null
  node: string
  simulated: boolean
}

export default function RiskTelemetryChart({ data }: { data: RiskPoint[] }) {
  const devicePoints = data.filter((point) => !point.simulated)
  const simulatedPoints = data.filter((point) => point.simulated)
  return (
    <>
      <div className="chart-wrap" role="img" aria-label="Recent risk scores, separated by simulation provenance">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="#ffffff0d" vertical={false} />
          <XAxis
            dataKey="timeMs"
            type="number"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(value: number) => formatTimestamp(new Date(value).toISOString())}
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#788b84', fontSize: 10 }}
            minTickGap={30}
          />
          <YAxis dataKey="score" type="number" domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: '#788b84', fontSize: 10 }} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const point = payload[0].payload as RiskPoint
              return (
                <div className="risk-tooltip">
                  <strong>{point.time || String(label)}</strong>
                  <span>{point.score} / 100 · {point.node}</span>
                  <small>{point.simulated ? 'SIMULATED DATA' : 'NON-SIMULATED DATA'}</small>
                </div>
              )
            }}
          />
          <Scatter name="Non-simulated reading" data={devicePoints} fill="#55d99d" />
          <Scatter name="Simulated reading" data={simulatedPoints} fill="#49d9e6" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only" aria-label="Recent risk assessments">
        {data.map((point, index) => (
          <li key={`${point.node}-${point.timeMs}-${index}`}>
            {point.time}: risk score {point.score} for {point.node}; {point.simulated ? 'simulated' : 'non-simulated'} data.
          </li>
        ))}
      </ul>
    </>
  )
}
