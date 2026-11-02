import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
// Fonte embutida (não do Google Fonts): a rede do robô no laboratório não tem
// internet, e a tela tem de abrir igual sem ela. O resto da tela usa a fonte
// do sistema (system-ui, em App.jsx).
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
