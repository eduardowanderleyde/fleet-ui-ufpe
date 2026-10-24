import '@testing-library/jest-dom/vitest'

// jsdom não implementa canvas nem ResizeObserver — useMapCanvas.js usa os
// dois incondicionalmente ao montar (getContext('2d') pro draw(), um
// ResizeObserver pro redimensionamento). Sem esses stubs qualquer teste que
// monte MapView quebra antes de chegar na lógica que se quer testar.
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const fake2DContext = new Proxy({}, {
  get: (_target, prop) => {
    if (prop === 'canvas') return undefined
    return () => ({})
  },
  set: () => true,
})

HTMLCanvasElement.prototype.getContext = () => fake2DContext
