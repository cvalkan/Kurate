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
  ChevronDown
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
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Search failed");
      console.error(error);
    } finally {
      setSearching(false);
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
      
      const response = await axios.post(`${API}/tournaments`, {
        category: (category && category !== "any") ? category : "custom",
        papers: selectedPaperObjects,
        parallel_agents: parallelAgents,
        deep_analysis: deepAnalysis,
        search_query: searchDescription
      });
      
      const tournamentId = response.data.tournament.id;
      toast.success("Tournament created! Starting...");
      
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
                  <span className="text-sm font-mono text-muted-foreground">
                    {maxResults}
                  </span>
                </div>
                <Slider
                  value={[maxResults]}
                  onValueChange={(v) => setMaxResults(v[0])}
                  min={5}
                  max={100}
                  step={5}
                  data-testid="max-results-slider"
                />
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
                  Search
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
                        // Trim selection to 10
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

                {/* Warning for many papers */}
                {!deepAnalysis && selectedPapers.size > 15 && (
                  <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-50 p-2 rounded">
                    <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                    <span>
                      {totalMatches} comparisons will take ~{Math.ceil(totalMatches * 3 / parallelAgents / 60)} min
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
                    <span>Total comparisons:</span>
                    <span className="font-mono">{totalMatches}</span>
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
