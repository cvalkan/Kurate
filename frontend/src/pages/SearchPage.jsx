import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { format } from "date-fns";
import { 
  Search, 
  Loader2, 
  ArrowRight,
  FileSearch,
  Users,
  Calendar as CalendarIcon,
  Filter,
  X,
  CheckCircle2,
  ExternalLink,
  Trophy,
  AlertTriangle,
  Zap,
  Settings2,
  ChevronDown,
  Quote,
  Clock
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CATEGORIES = [
  { id: "cs.AI", name: "Artificial Intelligence" },
  { id: "cs.CL", name: "Computation and Language" },
  { id: "cs.CV", name: "Computer Vision" },
  { id: "cs.LG", name: "Machine Learning" },
  { id: "cs.NE", name: "Neural and Evolutionary Computing" },
  { id: "cs.RO", name: "Robotics" },
  { id: "cs.SE", name: "Software Engineering" },
  { id: "cs.CR", name: "Cryptography and Security" },
  { id: "cs.DB", name: "Databases" },
  { id: "cs.DC", name: "Distributed Computing" },
  { id: "stat.ML", name: "Machine Learning (Statistics)" },
  { id: "physics.gen-ph", name: "General Physics" },
  { id: "physics.comp-ph", name: "Computational Physics" },
  { id: "math.NA", name: "Numerical Analysis" },
  { id: "math.OC", name: "Optimization and Control" },
  { id: "q-bio.NC", name: "Neurons and Cognition" },
  { id: "q-bio.GN", name: "Genomics" },
  { id: "econ.EM", name: "Econometrics" },
  { id: "astro-ph", name: "Astrophysics" },
  { id: "cond-mat", name: "Condensed Matter" },
  { id: "hep-th", name: "High Energy Physics - Theory" },
  { id: "quant-ph", name: "Quantum Physics" }
];

export default function SearchPage() {
  const navigate = useNavigate();
  
  // Search state
  const [keywords, setKeywords] = useState("");
  const [author, setAuthor] = useState("");
  const [category, setCategory] = useState("");
  const [dateFrom, setDateFrom] = useState(null);
  const [dateTo, setDateTo] = useState(null);
  const [maxResults, setMaxResults] = useState(30);
  
  // Results state
  const [papers, setPapers] = useState([]);
  const [selectedPapers, setSelectedPapers] = useState(new Set());
  const [searchDescription, setSearchDescription] = useState("");
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  
  // Tournament config state
  const [parallelAgents, setParallelAgents] = useState(3);
  const [deepAnalysis, setDeepAnalysis] = useState(false);
  const [creating, setCreating] = useState(false);
  
  // Model selection state
  const [availableModels, setAvailableModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(null);
  
  // UCB config state
  const [useUCB, setUseUCB] = useState(false);
  const [ucbExpanded, setUcbExpanded] = useState(false);
  const [ucbExploration, setUcbExploration] = useState(1.414);
  const [ucbMinComparisons, setUcbMinComparisons] = useState(3);
  const [ucbMaxComparisons, setUcbMaxComparisons] = useState(null);
  const [ucbTargetTopK, setUcbTargetTopK] = useState(null);
  const [ucbConfidenceLevel, setUcbConfidenceLevel] = useState(0.95);
  const [loadingCitations, setLoadingCitations] = useState(false);

  // Fetch models on mount
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const response = await axios.get(`${API}/models`);
        setAvailableModels(response.data.models);
        setSelectedModel(response.data.default);
      } catch (error) {
        console.error("Failed to load models:", error);
      }
    };
    fetchModels();
  }, []);

  const handleSearch = async () => {
    if (!keywords && !author && !category) {
      toast.error("Please enter at least one search criteria");
      return;
    }
    
    setSearching(true);
    setHasSearched(true);
    
    try {
      const response = await axios.post(`${API}/papers/search`, {
        keywords: keywords || null,
        author: author || null,
        category: (category && category !== "any") ? category : null,
        date_from: dateFrom ? format(dateFrom, "yyyy-MM-dd") : null,
        date_to: dateTo ? format(dateTo, "yyyy-MM-dd") : null,
        max_results: maxResults
      });
      
      setPapers(response.data.papers);
      setSearchDescription(response.data.search_description);
      setSelectedPapers(new Set()); // Reset selection
      
      if (response.data.papers.length === 0) {
        toast.info("No papers found. Try different search criteria.");
      } else {
        toast.success(`Found ${response.data.papers.length} papers`);
        
        // Fetch citations in background (non-blocking)
        fetchCitations(response.data.papers);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Search failed");
      console.error(error);
    } finally {
      setSearching(false);
    }
  };

  const fetchCitations = async (paperList) => {
    if (!paperList || paperList.length === 0) return;
    
    setLoadingCitations(true);
    try {
      const arxivIds = paperList.map(p => p.arxiv_id);
      const response = await axios.post(`${API}/papers/citations`, { arxiv_ids: arxivIds });
      const citations = response.data.citations;
      
      // Only update if we got some citations
      if (Object.keys(citations).length > 0) {
        setPapers(prevPapers => 
          prevPapers.map(p => ({
            ...p,
            citation_count: citations[p.arxiv_id] ?? null
          }))
        );
      }
    } catch (error) {
      console.log("Citations fetch skipped:", error.message);
    } finally {
      setLoadingCitations(false);
    }
  };

  const togglePaperSelection = (paperId) => {
    const newSelection = new Set(selectedPapers);
    if (newSelection.has(paperId)) {
      newSelection.delete(paperId);
    } else {
      if (deepAnalysis && newSelection.size >= 10) {
        toast.error("Maximum 10 papers allowed in Deep Analysis mode");
        return;
      }
      newSelection.add(paperId);
    }
    setSelectedPapers(newSelection);
  };

  const selectAll = () => {
    const maxPapers = deepAnalysis ? 10 : papers.length;
    const toSelect = papers.slice(0, maxPapers).map(p => p.id);
    setSelectedPapers(new Set(toSelect));
  };

  const clearSelection = () => {
    setSelectedPapers(new Set());
  };

  const handleStartTournament = async () => {
    if (selectedPapers.size < 2) {
      toast.error("Please select at least 2 papers");
      return;
    }
    
    setCreating(true);
    
    try {
      // Get selected paper objects
      const selectedPaperObjects = papers.filter(p => selectedPapers.has(p.id));
      
      // Build request
      const requestData = {
        category: (category && category !== "any") ? category : "custom",
        papers: selectedPaperObjects,
        parallel_agents: parallelAgents,
        deep_analysis: deepAnalysis,
        search_query: searchDescription,
        ranking_mode: useUCB ? "ucb" : "round_robin",
        llm_model: selectedModel
      };
      
      // Add UCB config if enabled
      if (useUCB) {
        requestData.ucb_config = {
          exploration_constant: ucbExploration,
          min_comparisons_per_paper: ucbMinComparisons,
          max_total_comparisons: ucbMaxComparisons,
          convergence_threshold: 0.05,
          target_top_k: ucbTargetTopK,
          confidence_level: ucbConfidenceLevel
        };
      }
      
      const response = await axios.post(`${API}/tournaments`, requestData);
      
      const tournamentId = response.data.tournament.id;
      const modeMsg = useUCB ? "UCB tournament created!" : "Tournament created!";
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
      setCreating(false);
    }
  };

  const clearFilters = () => {
    setKeywords("");
    setAuthor("");
    setCategory("");
    setDateFrom(null);
    setDateTo(null);
  };

  const totalMatches = (selectedPapers.size * (selectedPapers.size - 1)) / 2;
  
  // UCB estimated matches - depends on mode (top-k vs full ranking) and confidence level
  // Higher confidence requires more comparisons: 0.80 -> 1.0x, 0.95 -> 1.3x, 0.99 -> 1.6x
  const confidenceMultiplier = 1 + (ucbConfidenceLevel - 0.80) * 3;
  
  const ucbEstimatedMatches = useUCB && selectedPapers.size > 0
    ? ucbMaxComparisons || Math.ceil((ucbTargetTopK 
        ? ucbTargetTopK * Math.log(selectedPapers.size) * 4 + selectedPapers.size * 2
        : selectedPapers.size * Math.log(selectedPapers.size) * 3) * confidenceMultiplier)
    : totalMatches;
  
  const effectiveMatches = useUCB ? ucbEstimatedMatches : totalMatches;
  const savedComparisons = totalMatches - ucbEstimatedMatches;

  return (
    <div className="container-main py-8" data-testid="search-page">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-heading-2 flex items-center gap-3 mb-2">
          <Search className="h-8 w-8 text-accent" />
          Search Papers
        </h1>
        <p className="text-muted-foreground">
          Search arXiv papers by keywords, author, category, or date to create a custom tournament
        </p>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Search Filters */}
        <div className="lg:col-span-1">
          <Card data-testid="search-filters-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Filter className="h-5 w-5" />
                Search Filters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Keywords */}
              <div className="space-y-2">
                <Label htmlFor="keywords">Keywords</Label>
                <Input
                  id="keywords"
                  placeholder="e.g., transformer, attention"
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  data-testid="keywords-input"
                />
                <p className="text-xs text-muted-foreground">
                  Searches in title and abstract
                </p>
              </div>

              {/* Author */}
              <div className="space-y-2">
                <Label htmlFor="author">Author</Label>
                <Input
                  id="author"
                  placeholder="e.g., Hinton, LeCun"
                  value={author}
                  onChange={(e) => setAuthor(e.target.value)}
                  data-testid="author-input"
                />
              </div>

              {/* Category */}
              <div className="space-y-2">
                <Label>Category (optional)</Label>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger data-testid="category-select">
                    <SelectValue placeholder="Any category" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">Any category</SelectItem>
                    {CATEGORIES.map((cat) => (
                      <SelectItem key={cat.id} value={cat.id}>
                        {cat.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Date From */}
              <div className="space-y-2">
                <Label>From Date</Label>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="w-full justify-start text-left font-normal"
                      data-testid="date-from-btn"
                    >
                      <CalendarIcon className="mr-2 h-4 w-4" />
                      {dateFrom ? format(dateFrom, "PPP") : "Select date"}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <Calendar
                      mode="single"
                      selected={dateFrom}
                      onSelect={setDateFrom}
                      initialFocus
                    />
                  </PopoverContent>
                </Popover>
              </div>

              {/* Date To */}
              <div className="space-y-2">
                <Label>To Date</Label>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="w-full justify-start text-left font-normal"
                      data-testid="date-to-btn"
                    >
                      <CalendarIcon className="mr-2 h-4 w-4" />
                      {dateTo ? format(dateTo, "PPP") : "Select date"}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <Calendar
                      mode="single"
                      selected={dateTo}
                      onSelect={setDateTo}
                      initialFocus
                    />
                  </PopoverContent>
                </Popover>
              </div>

              {/* Max Results */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Max Results</Label>
                  <span className={`text-sm font-mono ${maxResults > 50 ? 'text-amber-600' : 'text-muted-foreground'}`}>
                    {maxResults}
                    {maxResults > 50 && ' (slower)'}
                  </span>
                </div>
                <Slider
                  value={[maxResults]}
                  onValueChange={(v) => setMaxResults(v[0])}
                  min={10}
                  max={100}
                  step={10}
                  data-testid="max-results-slider"
                />
                {maxResults > 50 && (
                  <p className="text-xs text-amber-600">
                    ⚠️ Large searches may take 15-30 seconds due to arXiv rate limits
                  </p>
                )}
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-2">
                <Button 
                  onClick={handleSearch} 
                  disabled={searching}
                  className="flex-1"
                  data-testid="search-btn"
                >
                  {searching ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <Search className="h-4 w-4 mr-2" />
                  )}
                  {searching && maxResults > 50 ? 'Searching (this may take a while)...' : 'Search'}
                </Button>
                <Button 
                  variant="outline" 
                  onClick={clearFilters}
                  data-testid="clear-filters-btn"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Tournament Config - shows when papers selected */}
          {selectedPapers.size >= 2 && (
            <Card className="mt-4" data-testid="tournament-config-card">
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Trophy className="h-5 w-5 text-accent" />
                  Tournament Settings
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
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
                  />
                </div>

                {/* Deep Analysis */}
                <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/50">
                  <div className="flex items-center gap-2">
                    <FileSearch className="h-4 w-4 text-accent" />
                    <Label htmlFor="deep-analysis-search" className="cursor-pointer">
                      Deep Analysis
                    </Label>
                  </div>
                  <Switch
                    id="deep-analysis-search"
                    checked={deepAnalysis}
                    onCheckedChange={(checked) => {
                      setDeepAnalysis(checked);
                      if (checked && selectedPapers.size > 10) {
                        const trimmed = Array.from(selectedPapers).slice(0, 10);
                        setSelectedPapers(new Set(trimmed));
                        toast.info("Selection trimmed to 10 papers for Deep Analysis");
                      }
                    }}
                    data-testid="deep-analysis-toggle"
                  />
                </div>

                {deepAnalysis && (
                  <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-50 p-2 rounded">
                    <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                    <span>Downloads full PDFs. Slower but more thorough.</span>
                  </div>
                )}

                {/* UCB Mode */}
                <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/50">
                  <div className="flex items-center gap-2">
                    <Zap className="h-4 w-4 text-green-600" />
                    <Label htmlFor="ucb-mode" className="cursor-pointer">
                      UCB Smart Ranking
                    </Label>
                  </div>
                  <Switch
                    id="ucb-mode"
                    checked={useUCB}
                    onCheckedChange={setUseUCB}
                    data-testid="ucb-toggle"
                  />
                </div>

                {useUCB && (
                  <>
                    <div className="flex items-center gap-2 text-xs text-green-700 bg-green-50 p-2 rounded">
                      <Zap className="h-3.5 w-3.5 flex-shrink-0" />
                      <span>
                        Saves ~{savedComparisons > 0 ? savedComparisons : 0} comparisons vs round-robin
                      </span>
                    </div>
                    
                    {/* UCB Parameters (Expandable) */}
                    <Collapsible open={ucbExpanded} onOpenChange={setUcbExpanded}>
                      <CollapsibleTrigger className="flex items-center justify-between w-full p-2 text-xs text-muted-foreground hover:bg-secondary/50 rounded">
                        <div className="flex items-center gap-2">
                          <Settings2 className="h-3 w-3" />
                          <span>UCB Parameters</span>
                        </div>
                        <ChevronDown className={`h-3 w-3 transition-transform ${ucbExpanded ? 'rotate-180' : ''}`} />
                      </CollapsibleTrigger>
                      <CollapsibleContent className="space-y-3 pt-2">
                        <div className="space-y-3 p-3 bg-secondary/30 rounded-lg text-xs">
                          {/* Target Top-K */}
                          <div className="space-y-1">
                            <div className="flex justify-between">
                              <Label className="text-xs font-medium">Target Top-K</Label>
                              <span className="font-mono">{ucbTargetTopK || 'all'}</span>
                            </div>
                            <Slider
                              value={[ucbTargetTopK || selectedPapers.size]}
                              onValueChange={(v) => setUcbTargetTopK(v[0] >= selectedPapers.size ? null : v[0])}
                              min={3}
                              max={selectedPapers.size}
                              step={1}
                            />
                            <p className="text-[10px] text-muted-foreground">
                              Focus on finding accurate top-k papers (saves comparisons)
                            </p>
                          </div>
                          
                          {/* Confidence Level */}
                          <div className="space-y-1">
                            <div className="flex justify-between">
                              <Label className="text-xs">Confidence Level</Label>
                              <span className="font-mono">{(ucbConfidenceLevel * 100).toFixed(0)}%</span>
                            </div>
                            <Slider
                              value={[ucbConfidenceLevel]}
                              onValueChange={(v) => setUcbConfidenceLevel(v[0])}
                              min={0.80}
                              max={0.99}
                              step={0.01}
                            />
                            <p className="text-[10px] text-muted-foreground">
                              Higher = more certain rankings, more comparisons needed
                            </p>
                          </div>
                          
                          <div className="border-t border-border/50 pt-2 mt-2">
                            <p className="text-[10px] text-muted-foreground font-medium mb-2">Advanced</p>
                          </div>
                          
                          {/* Exploration Constant */}
                          <div className="space-y-1">
                            <div className="flex justify-between">
                              <Label className="text-xs">Exploration (c)</Label>
                              <span className="font-mono">{ucbExploration.toFixed(2)}</span>
                            </div>
                            <Slider
                              value={[ucbExploration]}
                              onValueChange={(v) => setUcbExploration(v[0])}
                              min={0.5}
                              max={3}
                              step={0.1}
                            />
                            <p className="text-[10px] text-muted-foreground">
                              Higher = more exploration of uncertain papers
                            </p>
                          </div>
                          
                          {/* Min Comparisons */}
                          <div className="space-y-1">
                            <div className="flex justify-between">
                              <Label className="text-xs">Min comparisons/paper</Label>
                              <span className="font-mono">{ucbMinComparisons}</span>
                            </div>
                            <Slider
                              value={[ucbMinComparisons]}
                              onValueChange={(v) => setUcbMinComparisons(v[0])}
                              min={2}
                              max={10}
                              step={1}
                            />
                          </div>
                          
                          {/* Max Total Comparisons */}
                          <div className="space-y-1">
                            <div className="flex justify-between">
                              <Label className="text-xs">Max total comparisons</Label>
                              <span className="font-mono">{ucbMaxComparisons || 'auto'}</span>
                            </div>
                            <Slider
                              value={[ucbMaxComparisons || ucbEstimatedMatches]}
                              onValueChange={(v) => setUcbMaxComparisons(v[0])}
                              min={Math.ceil(selectedPapers.size * 2)}
                              max={totalMatches}
                              step={5}
                            />
                            <p className="text-[10px] text-muted-foreground">
                              Auto: ~{ucbEstimatedMatches} {ucbTargetTopK ? '(top-k mode)' : '(full ranking)'}
                            </p>
                          </div>
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  </>
                )}

                {/* Time Estimate & Warning */}
                {selectedPapers.size > 2 && (
                  <div className={`flex items-center gap-2 text-xs p-2 rounded ${
                    effectiveMatches > 100 ? 'text-amber-600 bg-amber-50' : 'text-muted-foreground bg-secondary/30'
                  }`}>
                    <Clock className="h-3.5 w-3.5 flex-shrink-0" />
                    <span>
                      Est. time: ~{Math.ceil(effectiveMatches * 2.5 / parallelAgents / 60)} min
                      {effectiveMatches > 200 && ' (large tournament)'}
                    </span>
                  </div>
                )}

                {/* Stats */}
                <div className="text-sm text-muted-foreground border-t border-border pt-3 space-y-1">
                  <div className="flex justify-between">
                    <span>Selected papers:</span>
                    <span className="font-mono">{selectedPapers.size}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>{useUCB ? 'Est. comparisons:' : 'Total comparisons:'}</span>
                    <span className="font-mono">
                      {useUCB ? `~${ucbEstimatedMatches}` : totalMatches}
                      {useUCB && totalMatches > 0 && <span className="text-green-600 ml-1">({Math.round((1 - ucbEstimatedMatches/totalMatches) * 100)}% less)</span>}
                    </span>
                  </div>
                </div>

                {/* Start Button */}
                <Button
                  className="w-full"
                  onClick={handleStartTournament}
                  disabled={creating || selectedPapers.size < 2}
                  data-testid="start-tournament-btn"
                >
                  {creating ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <Trophy className="h-4 w-4 mr-2" />
                  )}
                  Start Tournament
                  <ArrowRight className="h-4 w-4 ml-2" />
                </Button>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Results */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg">
                    {hasSearched ? `Search Results (${papers.length})` : "Search Results"}
                  </CardTitle>
                  {searchDescription && (
                    <CardDescription className="mt-1">
                      {searchDescription}
                    </CardDescription>
                  )}
                </div>
                {papers.length > 0 && (
                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      size="sm" 
                      onClick={selectAll}
                      data-testid="select-all-btn"
                    >
                      Select All
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm" 
                      onClick={clearSelection}
                      disabled={selectedPapers.size === 0}
                      data-testid="clear-selection-btn"
                    >
                      Clear ({selectedPapers.size})
                    </Button>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {!hasSearched ? (
                <div className="text-center py-16 text-muted-foreground">
                  <Search className="h-16 w-16 mx-auto mb-4 opacity-30" />
                  <p>Enter search criteria and click Search to find papers</p>
                </div>
              ) : searching ? (
                <div className="text-center py-16">
                  <Loader2 className="h-12 w-12 animate-spin mx-auto mb-4 text-accent" />
                  <p className="text-muted-foreground">Searching arXiv...</p>
                </div>
              ) : papers.length === 0 ? (
                <div className="text-center py-16 text-muted-foreground">
                  <FileSearch className="h-16 w-16 mx-auto mb-4 opacity-30" />
                  <p>No papers found. Try different search criteria.</p>
                </div>
              ) : (
                <ScrollArea className="h-[600px] pr-4">
                  <div className="space-y-3">
                    {papers.map((paper, index) => {
                      const isSelected = selectedPapers.has(paper.id);
                      return (
                        <div
                          key={paper.id}
                          className={`p-4 rounded-lg border transition-all cursor-pointer ${
                            isSelected 
                              ? "border-accent bg-accent/5" 
                              : "border-border hover:border-accent/50"
                          }`}
                          onClick={() => togglePaperSelection(paper.id)}
                          data-testid={`paper-result-${index}`}
                        >
                          <div className="flex items-start gap-3">
                            <div className="pt-1">
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={() => togglePaperSelection(paper.id)}
                                onClick={(e) => e.stopPropagation()}
                              />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-start justify-between gap-2">
                                <h3 className="font-medium text-sm leading-tight">
                                  {paper.title}
                                </h3>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="h-6 w-6 flex-shrink-0"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    window.open(paper.link, "_blank");
                                  }}
                                >
                                  <ExternalLink className="h-3 w-3" />
                                </Button>
                              </div>
                              
                              <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                                <Users className="h-3 w-3" />
                                <span className="truncate">
                                  {paper.authors?.slice(0, 3).join(", ")}
                                  {paper.authors?.length > 3 && " et al."}
                                </span>
                              </div>
                              
                              <div className="flex items-center gap-2 mt-2 flex-wrap">
                                <Badge variant="secondary" className="text-xs font-mono">
                                  {paper.arxiv_id}
                                </Badge>
                                <span className="text-xs text-muted-foreground">
                                  {paper.published?.slice(0, 10)}
                                </span>
                                {paper.citation_count !== null && paper.citation_count !== undefined ? (
                                  <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 bg-amber-50">
                                    <Quote className="h-2.5 w-2.5 mr-1" />
                                    {paper.citation_count} citations
                                  </Badge>
                                ) : loadingCitations && (
                                  <Badge variant="outline" className="text-xs border-muted text-muted-foreground animate-pulse">
                                    <Loader2 className="h-2.5 w-2.5 mr-1 animate-spin" />
                                    citations...
                                  </Badge>
                                )}
                                {paper.categories?.slice(0, 2).map(cat => (
                                  <Badge key={cat} variant="outline" className="text-xs">
                                    {cat}
                                  </Badge>
                                ))}
                              </div>
                              
                              <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
                                {paper.abstract}
                              </p>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
