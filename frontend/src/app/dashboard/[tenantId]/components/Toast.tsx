'use client'

import { motion, AnimatePresence } from 'framer-motion'

export function Toast({ message }: { message: string | null }) {
  return (
    <AnimatePresence>
      {message && (
        <motion.div
          className="db-toast"
          initial={{ opacity: 0, y: -16, x: '-50%' }}
          animate={{ opacity: 1, y: 0, x: '-50%' }}
          exit={{ opacity: 0, y: -16, x: '-50%' }}
        >
          {message}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
