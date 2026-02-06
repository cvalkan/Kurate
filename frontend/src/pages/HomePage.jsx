import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { 
  FlaskConical, 
  Zap, 
  Trophy, 
  ArrowRight, 
  Sparkles,
  Brain,
  Cpu,
  Atom,
  FileSearch,
  Clock,
  AlertTriangle
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const categoryIcons = {
  "cs.AI": Brain,
  "cs.LG": Cpu,
  "cs.CV": Sparkles,
  "physics.gen-ph": Atom,
  "quant-ph": Atom,
};

export default function HomePage() {
  const navigate = useNavigate();
  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState("");
  const [numPapers, setNumPapers] = useState(8);
  const [parallelAgents, setParallelAgents] = useState(3);
  const [deepAnalysis, setDeepAnalysis] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingCategories, setLoadingCategories] = useState(true);
  const [availableModels, setAvailableModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(null);
  const [availablePrompts, setAvailablePrompts] = useState([]);
  const [selectedPromptKey, setSelectedPromptKey] = useState("scientific_impact");

  useEffect(() => {
    fetchCategories();
    fetchModels();
    fetchPrompts();
  }, []);

  const fetchCategories = async () => {
    try {
      const response = await axios.get(`${API}/categories`);
      setCategories(response.data.categories);
    } catch (error) {
      toast.error("Failed to load categories");
      console.error(error);
    } finally {
      setLoadingCategories(false);
    }
  };

  const fetchModels = async () => {
    try {
      const response = await axios.get(`${API}/models`);
      setAvailableModels(response.data.models);
      setSelectedModel(response.data.default);
    } catch (error) {
      console.error("Failed to load models:", error);
    }
  };

  const fetchPrompts = async () => {
    try {
      const response = await axios.get(`${API}/prompts`);
      setAvailablePrompts(response.data.prompts);
      setSelectedPromptKey(response.data.default);
    } catch (error) {
      console.error("Failed to load prompts:", error);
    }
  };

  const handleStartTournament = async () => {
    if (!selectedCategory) {
      toast.error("Please select a category");
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(`${API}/tournaments`, {
        category: selectedCategory,
        num_papers: numPapers,
        parallel_agents: parallelAgents,
        deep_analysis: deepAnalysis,
        llm_model: selectedModel,
        prompt_key: selectedPromptKey
      });
      
      const tournamentId = response.data.tournament.id;
      const modeMsg = deepAnalysis ? "Deep Analysis tournament created!" : "Tournament created!";
      toast.success(`${modeMsg} Starting...`);
      
      // Start the tournament with retry
      try {
        await axios.post(`${API}/tournaments/${tournamentId}/start`);
      } catch (startError) {
        console.error("First start attempt failed, retrying...", startError);
        await new Promise(resolve => setTimeout(resolve, 500));
        await axios.post(`${API}/tournaments/${tournamentId}/start`);
      }
      
      // Navigate to tournament page
      navigate(`/tournament/${tournamentId}`);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to create tournament");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const getCategoryIcon = (categoryId) => {
    const Icon = categoryIcons[categoryId] || FlaskConical;
    return Icon;
  };

  const totalMatches = (numPapers * (numPapers - 1)) / 2;
  
  // Estimate time (rough estimate: 3s per comparison for standard, 10s for deep)
  const estimatedTime = deepAnalysis 
    ? Math.ceil((totalMatches * 10) / 60) + Math.ceil(numPapers * 0.5) // includes PDF download time
    : Math.ceil((totalMatches * 3) / parallelAgents / 60);

  return (
    <div className="min-h-[calc(100vh-4rem)]">
      {/* Hero Section */}
      <section className="relative overflow-hidden border-b border-border bg-gradient-to-b from-secondary/50 to-background">
        <div className="container-main py-16 md:py-24">
          <div className="grid gap-12 lg:grid-cols-2 lg:gap-16 items-center">
            <div className="space-y-6 animate-fade-in">
              <Badge variant="secondary" className="text-sm font-mono">
                Powered by GPT-5.2
              </Badge>
              <h1 className="text-heading-1 text-foreground">
                Discover High-Impact
                <span className="text-accent block">Scientific Papers</span>
              </h1>
              <p className="text-lg text-muted-foreground max-w-lg leading-relaxed">
                Fetch the latest arXiv papers and let AI determine their scientific impact 
                through pairwise tournament comparisons using Bradley-Terry scoring.
              </p>
              <div className="flex flex-wrap gap-4 pt-2">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Zap className="h-4 w-4 text-accent" />
                  <span>Parallel processing</span>
                </div>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Trophy className="h-4 w-4 text-amber-500" />
                  <span>Bradley-Terry rankings</span>
                </div>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <FileSearch className="h-4 w-4 text-green-600" />
                  <span>Deep analysis mode</span>
                </div>
              </div>
            </div>

            <div className="relative animate-slide-up" style={{ animationDelay: "0.2s" }}>
              <div className="absolute inset-0 bg-gradient-to-r from-accent/10 to-transparent rounded-2xl blur-3xl" />
              <Card 
                className="relative border-2 shadow-lg"
                data-testid="tournament-config-card"
              >
                <CardHeader>
                  <CardTitle className="font-heading text-xl">Start a Tournament</CardTitle>
                  <CardDescription>
                    Configure your paper ranking tournament
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Category Selection */}
                  <div className="space-y-2">
                    <Label htmlFor="category">ArXiv Category</Label>
                    <Select
                      value={selectedCategory}
                      onValueChange={setSelectedCategory}
                      disabled={loadingCategories}
                      data-testid="category-select"
                    >
                      <SelectTrigger id="category" data-testid="category-select-trigger">
                        <SelectValue placeholder="Select a category" />
                      </SelectTrigger>
                      <SelectContent>
                        {categories.map((cat) => {
                          const Icon = getCategoryIcon(cat.id);
                          return (
                            <SelectItem 
                              key={cat.id} 
                              value={cat.id}
                              data-testid={`category-option-${cat.id}`}
                            >
                              <div className="flex items-center gap-2">
                                <Icon className="h-4 w-4" />
                                <span>{cat.name}</span>
                                <span className="text-muted-foreground font-mono text-xs">
                                  ({cat.id})
                                </span>
                              </div>
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Number of Papers */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label>Number of Papers</Label>
                      <span className="text-sm font-mono text-muted-foreground">
                        {numPapers}
                      </span>
                    </div>
                    <Slider
                      value={[numPapers]}
                      onValueChange={(v) => setNumPapers(v[0])}
                      min={4}
                      max={deepAnalysis ? 10 : 20}
                      step={1}
                      data-testid="num-papers-slider"
                    />
                    <p className="text-xs text-muted-foreground">
                      {totalMatches} total comparisons
                    </p>
                  </div>

                  {/* Parallel Agents */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label>Parallel Agents</Label>
                      <span className="text-sm font-mono text-muted-foreground">
                        {parallelAgents}
                      </span>
                    </div>
                    <Slider
                      value={[parallelAgents]}
                      onValueChange={(v) => setParallelAgents(v[0])}
                      min={1}
                      max={5}
                      step={1}
                      disabled={deepAnalysis}
                      data-testid="parallel-agents-slider"
                    />
                    <p className="text-xs text-muted-foreground">
                      {deepAnalysis 
                        ? "Limited to 2 in deep analysis mode" 
                        : "Higher = faster, but may hit rate limits"}
                    </p>
                  </div>

                  {/* AI Model Selection */}
                  <div className="space-y-2">
                    <Label>AI Model</Label>
                    <Select
                      value={selectedModel ? `${selectedModel.provider}:${selectedModel.model}` : ""}
                      onValueChange={(value) => {
                        const [provider, model] = value.split(":");
                        setSelectedModel({ provider, model });
                      }}
                      data-testid="model-selector"
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select AI model" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableModels.map((m) => (
                          <SelectItem key={`${m.provider}:${m.model}`} value={`${m.provider}:${m.model}`}>
                            <div className="flex items-center gap-2">
                              <span>{m.name}</span>
                              {m.is_default && (
                                <Badge variant="outline" className="text-[10px] py-0">Default</Badge>
                              )}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Evaluation Prompt Selection */}
                  <div className="space-y-2">
                    <Label>Evaluation Criteria</Label>
                    <Select
                      value={selectedPromptKey}
                      onValueChange={setSelectedPromptKey}
                      data-testid="prompt-selector"
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select evaluation criteria" />
                      </SelectTrigger>
                      <SelectContent>
                        {availablePrompts.map((p) => (
                          <SelectItem key={p.key} value={p.key}>
                            <div className="flex items-center gap-2">
                              <span>{p.name}</span>
                              {p.is_default && (
                                <Badge variant="outline" className="text-[10px] py-0">Default</Badge>
                              )}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {selectedPromptKey && availablePrompts.find(p => p.key === selectedPromptKey) && (
                      <p className="text-xs text-muted-foreground">
                        {availablePrompts.find(p => p.key === selectedPromptKey)?.description}
                      </p>
                    )}
                  </div>

                  {/* Deep Analysis Toggle */}
                  <div className="space-y-3 p-4 rounded-lg bg-secondary/50 border border-border">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <FileSearch className="h-5 w-5 text-accent" />
                        <Label htmlFor="deep-analysis" className="font-medium cursor-pointer">
                          Deep Analysis Mode
                        </Label>
                      </div>
                      <Switch
                        id="deep-analysis"
                        checked={deepAnalysis}
                        onCheckedChange={(checked) => {
                          setDeepAnalysis(checked);
                          if (checked && numPapers > 10) {
                            setNumPapers(10);
                          }
                        }}
                        data-testid="deep-analysis-toggle"
                      />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {deepAnalysis ? (
                        <span className="flex items-start gap-1.5">
                          <span className="text-green-600 font-medium">ON:</span>
                          Downloads full PDFs and analyzes introduction, methodology, results & conclusion sections. More thorough but slower.
                        </span>
                      ) : (
                        <span className="flex items-start gap-1.5">
                          <span className="text-muted-foreground font-medium">OFF:</span>
                          Compares papers based on abstracts only. Fast but less detailed analysis.
                        </span>
                      )}
                    </p>
                    
                    {deepAnalysis && (
                      <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-50 p-2 rounded">
                        <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                        <span>Deep analysis is slower (~{estimatedTime} min). Limited to 10 papers max.</span>
                      </div>
                    )}
                  </div>

                  {/* Estimated Time */}
                  <div className="flex items-center justify-between text-sm text-muted-foreground border-t border-border pt-4">
                    <div className="flex items-center gap-2">
                      <Clock className="h-4 w-4" />
                      <span>Estimated time</span>
                    </div>
                    <span className="font-mono">
                      ~{estimatedTime < 1 ? "<1" : estimatedTime} min
                    </span>
                  </div>

                  {/* Start Button */}
                  <Button
                    className="w-full h-12 text-base"
                    onClick={handleStartTournament}
                    disabled={loading || !selectedCategory}
                    data-testid="start-tournament-btn"
                  >
                    {loading ? (
                      <span className="flex items-center gap-2">
                        <div className="h-4 w-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        {deepAnalysis ? "Creating Deep Analysis..." : "Creating Tournament..."}
                      </span>
                    ) : (
                      <span className="flex items-center gap-2">
                        {deepAnalysis && <FileSearch className="h-4 w-4" />}
                        {deepAnalysis ? "Start Deep Analysis" : "Start Tournament"}
                        <ArrowRight className="h-4 w-4" />
                      </span>
                    )}
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </section>

      {/* How it Works */}
      <section className="py-16 md:py-24">
        <div className="container-main">
          <div className="text-center mb-12">
            <h2 className="text-heading-2 mb-4">How It Works</h2>
            <p className="text-muted-foreground max-w-2xl mx-auto">
              Our AI-powered tournament system evaluates papers through systematic pairwise comparisons
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {[
              {
                step: "01",
                title: "Fetch Papers",
                description: "Select a category and we'll fetch the latest papers from arXiv sorted by submission date.",
                icon: FlaskConical
              },
              {
                step: "02", 
                title: "AI Comparison",
                description: "GPT-5.2 evaluates pairs of papers. Standard mode uses abstracts; Deep Analysis reads full PDFs.",
                icon: Brain
              },
              {
                step: "03",
                title: "Ranked Results",
                description: "Bradley-Terry scoring produces a final ranked list of papers by estimated scientific impact.",
                icon: Trophy
              }
            ].map((item, index) => (
              <Card 
                key={item.step} 
                className="relative overflow-hidden group card-interactive animate-slide-up"
                style={{ animationDelay: `${index * 0.1}s` }}
                data-testid={`how-it-works-step-${index + 1}`}
              >
                <CardContent className="pt-6">
                  <span className="absolute top-4 right-4 font-mono text-5xl font-bold text-secondary group-hover:text-accent/20 transition-colors">
                    {item.step}
                  </span>
                  <item.icon className="h-10 w-10 text-accent mb-4" />
                  <h3 className="font-heading font-semibold text-lg mb-2">{item.title}</h3>
                  <p className="text-sm text-muted-foreground">{item.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
