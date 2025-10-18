// Configuration
const API_BASE_URL = "http://localhost:8000" // Change this to your backend URL
let preferences = []

// DOM Elements
const preferenceInput = document.getElementById("preferenceInput")
const addBtn = document.getElementById("addBtn")
const tagsList = document.getElementById("tagsList")
const videoTitle = document.getElementById("videoTitle")
const videoDescription = document.getElementById("videoDescription")
const analyzeBtn = document.getElementById("analyzeBtn")
const resultsSection = document.getElementById("resultsSection")
const resultsList = document.getElementById("resultsList")
const loadingState = document.getElementById("loadingState")
const errorState = document.getElementById("errorState")
const errorMessage = document.getElementById("errorMessage")

// Load preferences from storage on popup open
document.addEventListener("DOMContentLoaded", () => {
  window.chrome.storage.local.get(["preferences"], (result) => {
    if (result.preferences) {
      preferences = result.preferences
      renderTags()
    }
  })
})

// Add preference
addBtn.addEventListener("click", addPreference)
preferenceInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") addPreference()
})

function addPreference() {
  const value = preferenceInput.value.trim()
  if (value && !preferences.includes(value)) {
    preferences.push(value)
    preferenceInput.value = ""
    renderTags()
    savePreferences()
  }
}

function removePreference(index) {
  preferences.splice(index, 1)
  renderTags()
  savePreferences()
}

function renderTags() {
  tagsList.innerHTML = preferences
    .map(
      (pref, index) => `
      <div class="tag">
        <span>${pref}</span>
        <span class="tag-remove" onclick="removePreference(${index})">×</span>
      </div>
    `,
    )
    .join("")
}

function savePreferences() {
  window.chrome.storage.local.set({ preferences })
}

// Analyze content
analyzeBtn.addEventListener("click", analyzeContent)

async function analyzeContent() {
  const title = videoTitle.value.trim()
  const description = videoDescription.value.trim()

  if (!title || !description) {
    showError("Please enter both title and description")
    return
  }

  if (preferences.length === 0) {
    showError("Please add at least one preference")
    return
  }

  showLoading(true)
  hideError()
  resultsSection.classList.add("hidden")

  try {
    const response = await fetch(`${API_BASE_URL}/classify`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        video_title: title,
        video_description: description,
        filter: preferences.join(", "),
      }),
    })

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`)
    }

    const data = await response.json()
    displayResults(data)
  } catch (error) {
    console.error("Error:", error)
    showError(`Failed to analyze: ${error.message}`)
  } finally {
    showLoading(false)
  }
}

function displayResults(data) {
  resultsSection.classList.remove("hidden")

  if (data.scores && typeof data.scores === "object") {
    resultsList.innerHTML = Object.entries(data.scores)
      .map(([label, score]) => {
        const percentage = Math.round(score * 100)
        return `
          <div class="result-item">
            <div class="result-label">${label}</div>
            <div class="result-bar">
              <div class="result-fill" style="width: ${percentage}%"></div>
            </div>
            <div class="result-score">${percentage}% match</div>
          </div>
        `
      })
      .join("")
  } else {
    resultsList.innerHTML = `<div class="result-item"><div class="result-label">${JSON.stringify(data)}</div></div>`
  }
}

function showLoading(show) {
  loadingState.classList.toggle("hidden", !show)
}

function showError(message) {
  errorMessage.textContent = message
  errorState.classList.remove("hidden")
}

function hideError() {
  errorState.classList.add("hidden")
}
