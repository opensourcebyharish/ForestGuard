import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet'
import { MapPinned } from 'lucide-react'
import type { NodeRecord } from '../api/forestguard'

function markerColor(node: NodeRecord) {
  if (node.latest_is_simulated) return '#49d9e6'
  if (node.current_risk_state === 'CRITICAL') return '#ff5d62'
  if (node.current_risk_state === 'WARNING') return '#ff9b52'
  if (node.current_risk_state === 'WATCH') return '#f0c45d'
  if (node.connectivity_state === 'OFFLINE') return '#7d8984'
  if (node.connectivity_state === 'STALE') return '#bb9a53'
  return '#51d99b'
}

export default function ForestMap({ nodes }: { nodes: NodeRecord[] }) {
  const plotted = nodes.filter((node) => Number.isFinite(node.latitude) && Number.isFinite(node.longitude))
  if (!plotted.length) {
    return (
      <div className="map-empty">
        <div className="map-empty-grid" aria-hidden="true" />
        <div className="map-empty-content"><span><MapPinned size={20} /></span><strong>Geospatial layer awaiting coordinates</strong><p>Stations appear on the map when latitude and longitude are available from the API.</p></div>
        <div className="map-empty-coordinates" aria-hidden="true">NO COORDINATE FIX&nbsp;&nbsp;·&nbsp;&nbsp; WGS84</div>
      </div>
    )
  }

  const center: [number, number] = [
    plotted.reduce((sum, node) => sum + (node.latitude ?? 0), 0) / plotted.length,
    plotted.reduce((sum, node) => sum + (node.longitude ?? 0), 0) / plotted.length,
  ]

  return (
    <div className="map-canvas" aria-label="Map of monitoring stations">
      <MapContainer center={center} zoom={plotted.length === 1 ? 8 : 5} scrollWheelZoom={false} zoomControl className="leaflet-map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {plotted.map((node) => (
          <CircleMarker
            key={node.node_id}
            center={[node.latitude as number, node.longitude as number]}
            radius={node.current_risk_state === 'CRITICAL' ? 9 : 7}
            pathOptions={{ color: markerColor(node), fillColor: markerColor(node), fillOpacity: 0.82, weight: 2 }}
          >
            <Tooltip direction="top">{node.name} · {node.current_risk_state ?? 'UNASSESSED'}</Tooltip>
            <Popup>
              <strong>{node.name}</strong><br />
              <span>{node.node_id}</span><br />
              <span>{node.connectivity_state} · {node.current_risk_state ?? 'UNASSESSED'}</span>
              {node.latest_is_simulated ? <><br /><span>SIMULATED DATA</span></> : null}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
