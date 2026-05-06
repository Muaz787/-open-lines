'use client'

import { useEffect, useRef } from 'react'

export default function Cursor() {
  const curRef = useRef<HTMLDivElement>(null)
  const ringRef = useRef<HTMLDivElement>(null)
  const pos = useRef({ mx: 0, my: 0, rx: 0, ry: 0 })

  useEffect(() => {
    if (window.matchMedia('(hover: none) and (pointer: coarse)').matches) return

    const onMove = (e: MouseEvent) => {
      pos.current.mx = e.clientX
      pos.current.my = e.clientY
      if (curRef.current) {
        curRef.current.style.left = `${e.clientX}px`
        curRef.current.style.top = `${e.clientY}px`
      }
    }

    const raf = () => {
      pos.current.rx += (pos.current.mx - pos.current.rx) * 0.1
      pos.current.ry += (pos.current.my - pos.current.ry) * 0.1
      if (ringRef.current) {
        ringRef.current.style.left = `${pos.current.rx}px`
        ringRef.current.style.top = `${pos.current.ry}px`
      }
      requestAnimationFrame(raf)
    }
    const rafId = requestAnimationFrame(raf)

    const expand = () => {
      if (ringRef.current) { ringRef.current.style.width = '42px'; ringRef.current.style.height = '42px' }
    }
    const shrink = () => {
      if (ringRef.current) { ringRef.current.style.width = '28px'; ringRef.current.style.height = '28px' }
    }

    document.addEventListener('mousemove', onMove)
    document.querySelectorAll('button, a, .toggle').forEach(el => {
      el.addEventListener('mouseenter', expand)
      el.addEventListener('mouseleave', shrink)
    })

    return () => {
      cancelAnimationFrame(rafId)
      document.removeEventListener('mousemove', onMove)
    }
  }, [])

  return (
    <>
      <div ref={curRef} id="cur" />
      <div ref={ringRef} id="cur-ring" />
    </>
  )
}
