import { Moon, Sun } from "lucide-react"
import { useTheme } from "@components/theme/themeProvider"

export function ModeToggle() {
  const { theme, setTheme } = useTheme()

  const toggleTheme = () => {
    setTheme(theme === "light" ? "dark" : "light")
  }

  return (
    <button
      onClick={toggleTheme}
      className=
        "p-2 rounded-full hover:bg-white/20 ease-in-out duration-200 transition-all"
    >
      {theme === "light" ? (
      <Sun className="h-5 w-5 transition-all text-white" />
      ) : (
      <Moon className="h-5 w-5 transition-all  text-neutral-400 text-xs" />
      )}
      </button>
  )
}

export default ModeToggle