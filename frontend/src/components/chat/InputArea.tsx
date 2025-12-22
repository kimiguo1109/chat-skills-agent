/**
 * InputArea - 聊天输入区域
 * 
 * 支持文本输入和附件上传
 */
import { useState, useCallback } from 'react'
import type { KeyboardEvent } from 'react'
import { FileUpload } from './FileUpload'

interface InputAreaProps {
  onSend: (message: string, fileUri?: string) => void
  isLoading: boolean
  userId?: string
}

export function InputArea({ onSend, isLoading, userId = 'anonymous' }: InputAreaProps) {
  const [input, setInput] = useState('')
  const [fileUri, setFileUri] = useState<string>('')
  const [uploadError, setUploadError] = useState<string>('')

  const handleSend = () => {
    if ((input.trim() || fileUri) && !isLoading) {
      onSend(input.trim(), fileUri)
      setInput('')
      setFileUri('')
    }
  }

  const handleKeyPress = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFileUploaded = useCallback((uri: string, _fileName: string) => {
    setFileUri(uri)
    setUploadError('')
  }, [])

  const handleUploadError = useCallback((error: string) => {
    setUploadError(error)
    setTimeout(() => setUploadError(''), 5000) // 5秒后清除错误
  }, [])

  return (
    <div className="space-y-2">
      {/* 上传错误提示 */}
      {uploadError && (
        <div className="px-3 py-2 text-sm text-red-600 bg-red-100 dark:bg-red-900/30 dark:text-red-400 rounded-lg">
          {uploadError}
        </div>
      )}
      
      <div className="flex items-center gap-2">
        {/* 文件上传按钮 */}
        <FileUpload
          onFileUploaded={handleFileUploaded}
          onError={handleUploadError}
          disabled={isLoading}
          userId={userId}
        />
        
        {/* 输入框 */}
        <div className="relative flex-1">
          <input 
            className="w-full h-12 px-4 pr-12 rounded-lg bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark focus:ring-2 focus:ring-primary focus:outline-none transition-shadow text-text-light-primary dark:text-text-dark-primary placeholder-text-light-secondary dark:placeholder-text-dark-secondary"
            placeholder={fileUri ? "输入指令（如：帮我出5道题）..." : "输入问题或上传附件..."}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyPress}
            disabled={isLoading}
          />
          <button 
            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center justify-center size-8 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
            onClick={handleSend}
            disabled={(!input.trim() && !fileUri) || isLoading}
          >
            <span className="material-symbols-outlined text-xl">send</span>
          </button>
        </div>
      </div>
    </div>
  )
}
